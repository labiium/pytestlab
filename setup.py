from setuptools import setup, find_packages

setup(
    name='pytestlab',
    version='0.1.1',
    description='A Python library for instrument automation and measurement data management.',
    author='Emmanuel Olowe',
    author_email='e.a.olowe@ed.ac.uk',
    url='https://github.com/labiium/PyTestLab',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        # 'numpy',
    #     # 'scipy',
        # 'pandas',
        # 'modin[ray]',
        # 'pyscpi',
        'pillow',
        # 'matplotlib',
    #     # 'pyvisa',
    ],
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
)
