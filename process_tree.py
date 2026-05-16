import os
import sys

def get_description(line):
    # Determine the actual item name from the tree structure
    # Typically tree output ends with the filename
    parts = line.strip().split(' ')
    name = parts[-1]
    
    is_dir = name.endswith('/') or line.strip().endswith('/')
    clean_name = name.rstrip('/')
    
    # Check if the name contains a dot to guess if it's a file, 
    # but be careful with hidden directories like .git/
    if not is_dir and '.' not in clean_name and not line.strip().endswith('/'):
        # If it doesn't have an extension and doesn't end in /, 
        # it might be a directory or a extension-less file.
        # However, the prompt says "mark directories as '目录'; files as '文件'"
        # In a standard tree, directories usually end with / or we use heuristics.
        pass

    type_str = '目录' if is_dir else '文件'
    
    ext = os.path.splitext(clean_name)[1].lower()
    desc = ''
    
    simple_map = {
        '.py': 'Python 源代码',
        '.md': 'Markdown 文档',
        '.txt': '文本文件',
        '.json': 'JSON 配置',
        '.yaml': 'YAML 配置',
        '.yml': 'YAML 配置',
        '.sh': 'Shell 脚本',
        '.png': '图像文件',
        '.jpg': '图像文件',
        '.jpeg': '图像文件',
        '.gif': '图像文件',
        '.css': 'CSS 样式',
        '.js': 'JavaScript 脚本',
        '.html': 'HTML 文档',
        '.sql': 'SQL 脚本',
        '.csv': 'CSV 数据',
        '.gitignore': 'Git 忽略配置',
        '.ipynb': 'Jupyter Notebook',
        '.toml': 'TOML 配置',
        '.db': '数据库文件'
    }
    
    desc = simple_map.get(ext, '')
    
    if not desc:
        if is_dir:
            desc = f'{clean_name} 目录'
        else:
            desc = f'{clean_name} 文件'
            
    return f'{type_str}: {desc}'

input_path = '/home/luosh/Whale/project_tree.txt'
output_dir = '/home/luosh/Whale/tmp'
output_path = os.path.join(output_dir, 'project_tree_with_descriptions.md')

os.makedirs(output_dir, exist_ok=True)

with open(input_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

with open(output_path, 'w', encoding='utf-8') as f:
    f.write('# Project Tree with Descriptions\n\n')
    for line in lines:
        raw_line = line.rstrip('\n')
        if not raw_line.strip(): continue
        desc = get_description(raw_line)
        # Combine the original tree line with the description
        f.write(f'{raw_line} # {desc}\n')

print(f'Output file: {output_path}')
print(f'Line count: {len(lines)}')
