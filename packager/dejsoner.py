import os
import json
import sys

def decompress_directory(input_file_path, output_dir):
    with open(input_file_path, 'r') as f:
        all_files_data = json.load(f)

    for relative_path, content in all_files_data.items():
        # Replace the directory separators to that of the current OS
        os_compatible_path = relative_path.replace('\\', os.sep)
        
        # Calculate the full path to create
        full_path = os.path.join(output_dir, os_compatible_path)
        directory = os.path.dirname(full_path)

        print(f'Decompressing: {relative_path}')
        print(f'Creating directory: {directory}')

        if not os.path.exists(directory):
            os.makedirs(directory)

        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)


    os.remove(input_file_path)
        
if __name__ == '__main__':
    if len(sys.argv) == 2:
        decompress_directory('pytestlab.json', sys.argv[1])
    else:
        decompress_directory('pytestlab.json', 'pytestlabs')
