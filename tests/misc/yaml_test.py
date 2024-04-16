import yaml

with open("D:/AKALI/PyTestLab/pytestlab/profiles/keysight/DSOX1204G.yaml", "r") as file:
    data = yaml.safe_load(file)
    print(data)