import os
import json
import sys

def compress_directory(input_dir, output_file_path):
    """
    Compresses a directory into a single JSON file.
    
    Parameters:
        input_dir (str): The directory to compress.
        output_file_path (str): The path to the output compressed file.
    """
    if not os.path.isdir(input_dir):
        print(f"Input directory {input_dir} does not exist.")
        return

    all_files_data = {}
    for root, dirs, files in os.walk(input_dir):
        # skip setup directory .git
        if '.git' in dirs:
            dirs.remove('.git')
        
        if 'packager' in dirs:
            dirs.remove('packager')

        if 'tests' in dirs:
            dirs.remove('tests')

        if '__pycache__' in dirs:
            dirs.remove('__pycache__')

        if 'requirements.txt' in files:
            files.remove('requirements.txt')
        
        if ".gitignore" in files:
            files.remove(".gitignore")
        
        if "pytestlab.egg-info" in dirs:
            dirs.remove("pytestlab.egg-info")
        
        if "examples" in dirs:
            dirs.remove("examples")

        if "pytestlab.json" in files:
            files.remove("pytestlab.json")
        
        for filename in files:
            filepath = os.path.join(root, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    file_data = f.read()
            except UnicodeDecodeError:
                print(f"Skipping file {filepath} as it cannot be read as UTF-8 text.")
                continue

            relative_path = os.path.relpath(filepath, input_dir)
            all_files_data[relative_path] = file_data

    with open(output_file_path, 'w', encoding='utf-8') as f:
        json.dump(all_files_data, f, ensure_ascii=False, indent=4)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python compress_directory_json.py <input_dir> <output_file_path>")
        sys.exit(1)
    input_dir = sys.argv[1]
    output_file_path = sys.argv[2]
    compress_directory(input_dir, output_file_path)
