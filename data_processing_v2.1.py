import requests
import time
import csv
import re
import os 
import subprocess #用来执行powershell命令并把输出重定向
from concurrent.futures import ThreadPoolExecutor #多线程池
access_token = "your_access_token" 

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
def get_branches_containing_commit(repo_path, commit_hash):
    # 检查仓库路径是否存在
    if not os.path.exists(repo_path):
        print(f"Error: {repo_path} does not exist")
        return []
    else:
        os.chdir(repo_path)
    
    # 执行 git branch --contains 命令
    try:
        result = subprocess.run(['git', 'branch', '-a', '--contains', commit_hash],
                                capture_output=True, text=True, check=True)
        branches = result.stdout.strip().split("\n")
        branches = [branch.strip().replace("* ", "") for branch in branches]  # 去掉当前分支的星号
        return branches
    except subprocess.CalledProcessError as e:
        error_message = e.stderr.strip()
        
        # 检查是否是 "no such commit" 错误
        if "no such commit" in error_message:
            print(f"该提交 {commit_hash} 所在的分支已经被移除")
        else:
            print(f"Error running git branch: {e}")
        return []
    
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


def is_meaningful_hunk(line):
    """
    判断给定的行是否是有意义的修改。
    
    参数:
        line (str): diff输出的一行内容。
        
    返回:
        bool: 如果行是有意义的修改，则返回True，否则返回False。
    """
    #去除首位的+ -
    if line.startswith('+') or line.startswith('-'):
        line = line[1:] 
    
    # 检查是否为空行
    if not line.strip():
        return False
    
    # 检查是否为缩进或空格
    if re.match(r'^\s+$', line):
        return False
    
    # 检查是否为import语句
    if re.match(r'^\s*import\s+', line):
        return False
    
    # 检查是否为单行注释
    if re.match(r'^\s*//.*$', line):
        return False

    # 检查是否是*开头的单行注释
    if re.match(r'^\s*\*\s',line):
        return False
    # 多行注释的起始
    if re.match(r'^\s*/\*.*', line) or re.match(r'^\s*/\*\*',line):
        return False
    
    # 多行注释的结束
    if re.match(r'.*\*/\s*$', line):
        return False
    

    return True
def extract_modified_functions(diff_lines,index):
    """
        提取给定diff输出中的修改函数名称。

        参数:
            diff_lines (list): 包含diff输出的行列表。
            index: 修改行的标号

        返回:
            str: 该修改块所在的函数名称。
        """
    function_name = None
    # open_braces = 0 # 追踪大括号的层次

    # 匹配@@行
    general = re.compile(r'@@.*?@@')
    # 匹配函数定义行的正则表达式
    function_general = re.compile(r'@@.*?@@\s*(.+)\s*\(')
    #捕获函数返回值，函数名，参数
    # 改进的函数匹配正则表达式
    function_pattern = re.compile(r'\b(?:public|private|protected|static|final|synchronized|abstract|native)?\s*(\w+(\[\])?)\s+(\w+)\s*\(.*?\)\s*\{')

    # 控制结构关键字列表
    control_keywords = {'if', 'else', 'for', 'while', 'switch', 'catch', 'finally', 'try'}

    # 记录当前是否处于修改块中
    in_modified_block = True
    get_func = False #是否找到函数

    # 向上查找函数名
    for j in range(index-1, -1, -1):
        prev_line = diff_lines[j] #上一行

        match_general = general.search(prev_line)  #匹配@@行
        function_match_general = function_general.search(prev_line) # 匹配@@后的函数
        function_match = function_pattern.search(prev_line) # 匹配函数定义行

        # 找到了最近的函数名
        if function_match:
            get_func = True
            function_name = function_match.group(3).strip()
            if function_name not in control_keywords:
                #print(prev_line)
                break  # 找到函数名，停止向上查找
            else:
                get_func = False
                function_name = None
                continue  # 跳过控制结构关键字

        # 如果一直找到@@还没找到函数，则在@@后的函数里  （疑问，新增的函数算否）
        if match_general and get_func==False:
            #print(prev_line+"@@@@@@@@@")
            in_modified_block = False # 遇到@@说明hunk块一定结束了
            if function_match_general:
                #print("@@@@@@"+prev_line)
                get_func = True
                function_name = function_match_general.group(1).strip()
            # print("############"+function_name)
            else:
                function_name = None
            break  # 找到函数名，停止向上查找

        #如果一个@@结束还没有找到函数
        if in_modified_block == False and get_func == False:
            break

    return function_name

def process_diff_output(repo,diff_output):
    # 处理每个diff并计算相关变量
    lines = diff_output.splitlines(keepends=False)
    is_new_diff =False#是否是新的diff
    file_count = 0 # 文件数（非test）
    java_file_count = 0 #java文件数
    func_count = 0 
    hunk_count = 0
    is_change = False # 用于标记是否开始了一个连续的hunk块
    is_test_case = False # 用于标记仓库内是否有test文件
    in_multiline_comment = False # 用于标记是否处于多行注释中
    funcset = [] # 去重
    have_test = 0 # 用于标记仓库内是否有test文件
    for i,line in enumerate(lines):
        #print(i)
        line = re.sub(r' {2,}', '', line)  # 删除多余空格

        # 检查是否是diff文件头
        if line.startswith("diff"):
            # is_change = False
            is_test_case = False
            match = re.search(r'/([^/]*)$', line)
            filename = match.group(1) if match else "" #获得修改文件的文件名
        
        # 检测是否是test文件
            if has_test_case(line) == False:
                file_count += 1

                #这个判定不是很准确吧，个人感觉制用检查java拓展名， 其他的jsp什么的直接过滤掉，xml更加应该直接删去
                if filename.endswith(".java") :#只检测JAVA文件
                    java_file_count += 1
                    is_new_diff = True
                else:
                    # print("not java file"+filename)
                    is_new_diff = False
                    continue
            else:
                # print("filaname :"+filename)
                is_test_case = True#跳过diff中的test文件
                is_new_diff = False
                have_test = 1
                continue
        
        
        # 统计有效的连续hunk
        # 不是修改行
        if(is_new_diff):
            
            if (line.startswith('+') == 0) and (line.startswith('-') == 0):
                is_change = 0

            # 是修改行
            if  ((line.startswith("+") == True and line.startswith("+++") == False) 
                or (line.startswith("-") == True and line.startswith("---") == False)) and (is_change == 0):

                # 判断是否在多行注释中
                if (re.match(r'^\s*/\*.*', line) or re.match(r'^\s*/\*\*',line)) and not in_multiline_comment:
                    in_multiline_comment = True
                elif re.match(r'.*\*/\s*$', line) and in_multiline_comment:
                    in_multiline_comment = False
                
                # 如果当前修改行在多行注释中，则跳过
                if in_multiline_comment and is_change ==0:
                    continue

                if is_meaningful_hunk(line):
                    # 找到一个有效hunk则寻找其所在func
                    func_name = extract_modified_functions(lines,i)
                    funcset.append(func_name)
                    is_change = 1
                    hunk_count = hunk_count + 1
                    
                else:
                    continue
               
    # 寻找test          
    if(have_test == 0) :
        #为什么要这么寻找test，test应该是只在diff中寻找就好了
        base_path='E:\\dachaung\\github_clone'
        is_test_case = count_test_files(os.path.join(base_path, repo))#判断仓库是否有test文件
    else:
        is_test_case = 0

    #统计func
    # funcset = extract_modified_functions(lines)
    unique_funcset = set(funcset)
    func_count = len(unique_funcset)
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

def clone_repository(url, output_dir):
    try:
        # 从URL中提取仓库名
        repository_name = re.search(r'/([^/]+/[^/]+)/commit/', url).group(1)
        repo = re.search(r'[^/]+$', repository_name).group()
        # 构造仓库地址
        repository_url = f"https://{access_token}@github.com/{repository_name}"
        api_url = f"https://api.github.com/repos/{repository_name}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        response = requests.get(api_url, headers=headers)

        if response.status_code == 200:
            # url有效
            # 检查目录下是否已经存在该仓库
            if os.path.exists(os.path.join(output_dir, repo)):
                #print(f"Repository {repo} already exists, skipping...")
                return
            # 在指定目录下执行git clone命令
            subprocess.run(["git", "clone", repository_url])
            print(f"Successfully cloned {url}")
            print(repository_name)
            # 延迟一段时间，避免频繁请求
            time.sleep(2)  # 可根据需要调整延迟时间
            return True
        else:
        #response.status_code == 404:
            return False
        
    except Exception as e:
        print(f"Error cloning {url}: {e}")
        
def main():
    base_path1='E:\\dachaung\\github_clone' #存放所有仓库的地方，一般是硬盘的目录
    output_file = "E:\\dachaung\\output.csv"#输出文件
    input_csv = "E:\\dachaung\\veracode_fliter.csv"#输入文件k
    # 表头
    header = ['index', 'cwe key word', 'matched key word', 'file', 'func', 'hunk', 'function_name', 'note', 'repo', 'branch', 'url','testcase']
    urls = []
    # 获取csv文件里的urls
    max_workers=5
    with open(input_csv) as csvfile:
        reader = csv.reader(csvfile)
        urls = [row[3] for row in reader]
    #  os.chdir(base_path1)
    # with ThreadPoolExecutor(max_workers=max_workers) as executor:
    #     for url in urls:
    #         executor.submit(clone_repository,url,base_path1)

    # CSV 文件写入
    with open(output_file, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()

        ###########手动筛选################
        cwe_key_word = {'CWE-79': ['XSS', 'Cross Site Scripting']}
        matched_key_word = {'CWE-79': ['XSS']}
        
        for index, url in enumerate(urls, start=1):
            # 获取diff内容diff_output
            match = re.search(r'/([^/]+/[^/]+)/commit/', url)
    
            if not match:
                
                result = {
                'index': index,
                'cwe key word': cwe_key_word,
                'matched key word': matched_key_word,
                'file': '0',
                'func': '0',
                'hunk': '0',
                'function_name': '',
                'note': "",  # 人工标注
                'repo': '',
                'branch': '',
                'url': url,
                'testcase': ''  
                }
                writer.writerow(result)
                continue
            
            repository_name = match.group(1)
            # note = get_commit_subject(commit_hash,repo) #获取commit的subject
        
                
            commit_hash = extract_commit_hash(url)
            os.chdir(base_path1)
            if clone_repository(url, base_path1) == False:
                continue#对应的url链接已经被删除不输出，共20条
            repo = re.search(r'[^/]+$', repository_name).group() #获取repo
            repo_path = os.path.join(base_path1, repo) #获取仓库的本地克隆目录
            branch = get_branches_containing_commit(repo_path, commit_hash) #获取分支名
            
            # os.chdir(os.path.join(base_path1, repo)) #改变当前工作目录到仓库的本地克隆目录
            diff_command = f'git diff {commit_hash}^..{commit_hash}'  # 注意添加了空格
            diff_output = subprocess.run(['powershell', '-Command', diff_command], capture_output=True, text=True, encoding='utf-8',errors='ignore' ).stdout
                #如果git diff命令的输出为空，从网络获取
            
            if diff_output is None or len(diff_output) < 1:
                print("the repo"+repo+" local is bad")
                diff_url = url + '.diff'
                res = requests.get(diff_url).text
                if res != None:
                    print("it is solved")
                    diff_output = res
            
            #print(diff_output) #调试一下
            
            with open(os.path.join(base_path1, repo, 'diff.txt'), 'w', encoding='utf-8') as file:
                file.write(diff_output)
            
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
