import os
import pickle
import sys

def compress_directory(input_dir, output_file_path):
    """
    Compresses a directory into a single compressed file.
    
    Parameters:
        input_dir (str): The directory to compress.
        output_file_path (str): The path to the output compressed file.
    """
    if not os.path.isdir(input_dir):
        print(f"Input directory {input_dir} does not exist.")
        return

    all_files_data = []
    for root, dirs, files in os.walk(input_dir):
        for filename in files:
            filepath = os.path.join(root, filename)
            with open(filepath, 'rb') as f:
                file_data = f.read()
            
            relative_path = os.path.relpath(filepath, input_dir)
            all_files_data.append((relative_path, file_data))
            
    with open(output_file_path, 'wb') as f:
        pickle.dump(all_files_data, f)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python compress_directory.py <input_dir> <output_file_path>")
        sys.exit(1)
    input_dir = sys.argv[1]
    output_file_path = sys.argv[2]
    compress_directory(input_dir, output_file_path)
