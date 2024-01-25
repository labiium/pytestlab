import ast
import os
import sys
from typing import List, Dict

class ClassVisitor(ast.NodeVisitor):
    def __init__(self, module_name):
        self.module_name = module_name
        self.items = []

    def visit_ClassDef(self, node):
        class_info = {
            'name': node.name, 
            'type': 'class', 
            'module': self.module_name,
            'docstring': ast.get_docstring(node),
            'methods': []
        }
        method_visitor = MethodVisitor(self.module_name)
        method_visitor.visit(node)
        class_info['methods'] = method_visitor.methods
        self.items.append(class_info)
        self.generic_visit(node)

class MethodVisitor(ast.NodeVisitor):
    def __init__(self, module_name):
        self.module_name = module_name
        self.methods = []

    def visit_FunctionDef(self, node):
        method_info = {
            'name': node.name,
            'type': 'method',
            'module': self.module_name,
            'docstring': ast.get_docstring(node)
        }
        self.methods.append(method_info)
        self.generic_visit(node)

def find_imports_in_init(init_path: str) -> Dict[str, str]:
    with open(init_path, 'r') as f:
        init_content = f.read()
    tree = ast.parse(init_content)
    imports = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                imports[name.name.split('.')[-1]] = name.name
        elif isinstance(node, ast.ImportFrom):
            for name in node.names:
                imports[name.name] = f"{node.module}.{name.name}"
    return imports

def get_import_path(name: str, module: str, directory_path: str, init_imports: Dict[str, str]) -> str:
    if name in init_imports:
        return init_imports[name]
    return module

def parse_python_file(file_path: str, module_name: str) -> List[dict]:
    with open(file_path, 'r') as file:
        tree = ast.parse(file.read())
        visitor = ClassVisitor(module_name)
        visitor.visit(tree)
        return visitor.items

def summarize_directory(directory_path: str) -> str:
    summary = []
    init_imports = find_imports_in_init(os.path.join(directory_path, '__init__.py')) if os.path.exists(os.path.join(directory_path, '__init__.py')) else {}
    for root, dirs, files in os.walk(directory_path):
        for file in files:
            if file.endswith('.py'):
                file_path = os.path.join(root, file)
                base_name = os.path.splitext(os.path.basename(file_path))[0]
                module_name = '.'.join(root.replace(directory_path, '').strip(os.sep).split(os.sep)) + ('.' + base_name if base_name != '__init__' else '')
                items = parse_python_file(file_path, module_name)
                for item in items:
                    import_path = get_import_path(item['name'], module_name, directory_path, init_imports)
                    summary.append(f"Import Path: {import_path}\n")
                    summary.append(f"  {item['type'].capitalize()}: {item['name']}\n")
                    if item['type'] == 'class':
                        for method in item['methods']:
                            summary.append(f"    Method: {method['name']}\n")
                            summary.append(f"    Docstring: {method['docstring']}\n")
                    summary.append(f"  Docstring: {item['docstring']}\n")
                    summary.append('\n')
    return ''.join(summary)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python compress_directory_json.py <input_dir> <output_file_path>")
        sys.exit(1)
    input_dir = sys.argv[1]
    output_file_path = sys.argv[2]
    summary = summarize_directory(input_dir)
    
    with open(output_file_path, 'w', encoding='utf-8') as f:
        f.write(summary)
