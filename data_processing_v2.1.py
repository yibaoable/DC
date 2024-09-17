import requests
import time
import csv
import re
import os 
import subprocess #用来执行powershell命令并把输出重定向

def has_test_case(line):
    """
    检查给定的diff输出行是否包含测试文件。

    参数:
        line (str): diff输出中的一行。

    返回:
        bool: 如果该行表示一个测试文件，则返回True，否则返回False。
    """
    assert isinstance(line, str)
    pattern = "^diff --git.*Test.*$"
    return bool(re.match(pattern, line, re.IGNORECASE))  # 忽略大小写

#统计仓库中test文件数量
#对这个函数的意义成疑问
def count_test_files(repo_path):
    """
    统计仓库中测试文件的数量。

    参数:
        repo_path (str): 仓库的路径。

    返回:
        bool: 如果仓库中包含测试文件，返回True，否则返回False。
    """
    # 定义测试文件的标志，比如文件名中包含 'test'，或位于 'tests' 目录
    test_keywords = ['test', 'tests']

    test_file_count = 0

    # 遍历目录和文件
    for root, dirs, files in os.walk(repo_path):
        for file in files:
            # 检查文件名或路径中是否包含测试关键字
            if any(keyword in file.lower() for keyword in test_keywords) or any(keyword in root.lower() for keyword in test_keywords):
                test_file_count += 1
    if test_file_count == 0:
        return False
    else:
        return True
    
#获取当前分支名
def get_current_branch(repo_path):
    try:
        # 使用 git 命令获取当前分支名
        #为什么这么写   肯定不是获取当前branch啊，而是根据commit修改获取branch
        #git branch --contains abcd1234
        result = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path,           # 指定仓库路径
            stdout=subprocess.PIPE,  # 捕获输出
            stderr=subprocess.PIPE,  # 捕获错误
            text=True                # 输出为文本形式
        )
        # 检查是否有错误
        if result.returncode != 0:
            print(f"Error: {result.stderr}")
            return None
        
        # 返回当前分支名称（去除末尾的换行符）
        return result.stdout.strip()
    
    except Exception as e:
        print(f"An error occurred: {e}")
        return None

def extract_commit_hash(url):
    """
    从给定的URL中提取提交哈希值。

    参数:
        url (str): 包含提交哈希值的URL。

    返回:
        str: 提取的提交哈希值，如果未找到则返回None。
    """
    # 匹配 commit_hash
    match = re.search(r'/commit/([^/#]+)', url)
    if match:
        commit_hash = match.group(1)
        return commit_hash
    else:
        return None




#这个函数的diff_line输入有一定问题啊
def extract_modified_functions(diff_lines):
    """
        提取给定diff输出中的修改函数名称。

        参数:
            diff_lines (list): 包含diff输出的行列表。

        返回:
            list: 修改的函数名称列表。
        """
    # 寻找func
    function_name = None
    functions_list = []
    # open_braces = 0 # 追踪大括号的层次

    # 匹配函数定义行的正则表达式
    function_general = re.compile(r'@@.*?@@\s*(.+)\s*\(')
    #捕获函数返回值，函数名，参数
    function_pattern = re.compile(r'\b(?:public|private|protected|static|final|synchronized|abstract|native)?\s*(\w+(\[\])?)\s+(\w+)\s*\(.*?\)\s*\{')

    # 记录当前是否处于修改块中
    in_modified_block = False
    get_func = False

    for i, line in enumerate(diff_lines):
        #这个逻辑不对，不应该是只从+或-开始搜索，而是需要确认是一个有效的修改块后在开始搜索
        if  ((line.startswith("+") == True and line.startswith("+++") == False) or (line.startswith("-") == True and line.startswith("---") == False)):
            in_modified_block = True
            get_func = False #是否找到函数

            # 向上查找函数名
            for j in range(i-1, 0, -1):
                prev_line = diff_lines[j] #上一行

                function_match_general = function_general.search(prev_line)
                function_match = function_pattern.search(prev_line)

                # 找到了最近的函数名
                if function_match:
                    get_func = True
                    function_name = function_match.group(1).strip()
                    #其实function_name not in functions_list是可以不要的，这点要子超确认
                    if function_name and function_name not in functions_list:
                        functions_list.append(function_name)
                    break  # 找到函数名，停止向上查找

                #这一块代码可能并不需要
                # 如果遇到另一个修改块，说明是同一个函数内的修改，停止向上查找
                if  ((prev_line.startswith("+") == True and prev_line.startswith("+++") == False) or (prev_line.startswith("-") == True and prev_line.startswith("---") == False)):
                    get_func = True
                    in_modified_block = False
                    break

                # 如果一直找到@@还没找到函数，则在@@后的函数里
                if function_match_general and get_func==0:
                    get_func = True
                    in_modified_block = False # 遇到@@说明hunk块一定结束了
                    function_name = function_match_general.group(1).strip()
                    #待确认
                    if function_name and function_name not in functions_list:
                        functions_list.append(function_name)
                    break  # 找到函数名，停止向上查找

                #如果没有找到函数
                if get_func == 0:
                    # 如果已经结束一个@@了，退出
                    if in_modified_block == False:
                        break
                    # 如果还没结束一个@@，接着找
                    else:
                        continue
        # 重置标志位
        else:
            in_modified_block = False

    return functions_list

def process_diff_output(repo,diff_output):
    # 处理每个diff并计算相关变量
    lines = diff_output.splitlines(keepends=False)

    file_count = 0 # 文件数（非test）
    java_file_count = 0 #java文件数
    func_count = 0 
    hunk_count = 0
    is_change = False # 用于标记是否开始了一个连续的hunk块
    is_test_case = False # 用于标记仓库内是否有test文件
    is_comment = False # 用于标记是否为注释
    funcset = set() # 去重
    have_test = 0 # 用于标记仓库内是否有test文件
    for line in lines:
        line = re.sub(r' {2,}', '', line)  # 删除多余空格

        # 检查是否是diff文件头
        if line.startswith("diff"):
            is_change = False
            is_test_case = False
            match = re.search(r'/([^/]*)$', line)
            filename = match.group(1) if match else "" #获得修改文件的文件名
        
        # 检测是否是test文件
            if has_test_case(line) == False:
                file_count += 1

                #这个判定不是很准确吧，个人感觉制用检查java拓展名， 其他的jsp什么的直接过滤掉，xml更加应该直接删去
                if filename.endswith(".java") or filename.endswith(".jsp") or filename.endswith(".jspx") or filename.endswith(".xml"):#只检测JAVA文件
                    java_file_count += 1
                else:
                    continue
            else:
                is_test_case = True#跳过diff中的test文件
                have_test = 1

        if is_test_case:
            continue

    # 统计有效的hunk
        # 不是修改行
        if (line.startswith('+') == 0) and (line.startswith('-') == 0):
            is_change = 0


        # 是修改行
        if  ((line.startswith("+") == True and line.startswith("+++") == False) 
            or (line.startswith("-") == True and line.startswith("---") == False)) and (is_change == 0):
            #这里的pass应该是continue把
            # 是import
            if (line.find("import") != -1) :
                pass
            # 跳过注释
                # 一行注释
            elif (line.find("//") == 1 ):
                pass
                # 是一段注释的开始
            elif (line.find('/**') == 1) or (line.find('/*') or (line.find('*')) == 1):
                is_comment = 1
                pass
                # 正在一段注释中
            elif (is_comment == 1):
                pass
                # 一段注释结束
            elif (line.find('*/') != -1) and is_comment == 1:
                is_comment = 0
                pass
            # 跳过空语句
            elif (len(line) == 1):
                pass
            # 跳过空语句
            #这个判定应该是不对的，line.strip()去掉空格后无论如何line中也还是有+或-的
            elif (len(line.strip()) == 0):
                # 跳过空行或者只包含空白字符的行
                pass
            # 跳过无效修改
            elif (line.isspace()):
                # 仅包含空白字符（缩进、空格）的行
                pass
            # 跳过无效修改
            # 是有效注释
            else :
                is_change = 1
                hunk = hunk + 1
    # 寻找test          
    if(have_test == 0) :
        #为什么要这么寻找test，test应该是只在diff中寻找就好了
        base_path='E:\\github_clone_repositories'
        is_test_case = count_test_files(os.path.join(base_path, repo))#判断仓库是否有test文件
    else:
        is_test_case = 1

    #统计func，这里是把diff的所有输出全部输入给函数，然后返回函数名
    funcset = extract_modified_functions(lines)
    func_count = len(funcset)
    note = ""  # 默认注释为空，后期人工检查时可填

# 构建结果数据
    datas = {
        'file': file_count,  # 统计文件数量以及Java文件数量
        'java_file_count': java_file_count,
        'func': func_count,  # 函数数量
        'hunk': hunk_count,  # 修改块数量
        'function_name': list(funcset),  # 函数名称列表
        'is_test_case': is_test_case #有无test
    }

    return datas

def main():
    base_path1='E:\\clone_diff' #存放所有仓库的地方，一般是硬盘的目录
    output_file = "data\\output.csv"#输出文件
    input_csv = "data\\veracode_fliter.csv.csv"#输入文件
    # 表头
    header = ['index', 'cwe key word', 'matched key word', 'file', 'func', 'hunk', 'function_name', 'note', 'repo', 'branch', 'url','testcase']
    urls = []
    # 获取csv文件里的urls
    with open(input_csv) as csvfile:
        reader = csv.reader(csvfile)
        urls = [row[3] for row in reader]

    # CSV 文件写入
    with open(output_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()

        ###########手动筛选################
        cwe_key_word = {'CWE-79': ['XSS', 'Cross Site Scripting']}
        matched_key_word = {'CWE-79': ['XSS']}
        
        for index, url in enumerate(urls, start=1):
            # 获取diff内容diff_output
            commit_hash = extract_commit_hash(url)
            repository_name = re.search(r'/([^/]+/[^/]+)/commit/', url).group(1) # 获取user/repo
            repo = re.search(r'[^/]+$', repository_name).group() #获取repo
            # note = get_commit_subject(commit_hash,repo) #获取commit的subject

            
            branch = get_current_branch(base_path1 + '\\' + repo) #获取当前分支名
            
            os.chdir(os.path.join(base_path1, repo)) #改变当前工作目录到仓库的本地克隆目录
            diff_command = f'git diff {commit_hash}^..{commit_hash}'  # 注意添加了空格
            diff_output = subprocess.run(['powershell', '-Command', diff_command], capture_output=True, text=True, encoding='utf-8').stdout
                #如果git diff命令的输出为空，从网络获取
            
            if len(diff_output) < 1:
                print("the repo local is bad")
                diff_url = url + '.diff'
                res = requests.get(diff_url).text
                if res != None:
                    print("it is solved")
                    diff_output = res
            #print(diff_output) #调试一下

            # 获取结果并写入CSV
            datas = process_diff_output(repo, diff_output)
            result = {
                'index': index,
                'cwe key word': cwe_key_word,
                'matched key word': matched_key_word,
                'file': f"{datas['file']}({datas['java_file_count']})",
                'func': datas['func'],
                'hunk': datas['hunk'],
                'function_name': datas['function_name'],
                'note': "",  # 人工标注
                'repo': repo,
                'branch': branch,
                'url': url,
                'testcase': int(datas['is_test_case'])  
            }
            writer.writerow(result)


    print(f"Data has been written to {output_file}")

if __name__ == '__main__':
    main()
