"""
Setup file for package `eddy`.
"""
from setuptools import find_packages, setup
import os

setup(name='eddy',
      description='eddy - recover precise rotation profiles of disks. Methods initially published in Teague et al. (2018).',
      long_description_content_type='text/markdown',
      long_description=open(os.path.join(
          os.path.dirname(__file__), 'README.md')).read(),
      url='https://github.com/richteague/eddy',
      author='Rich Teague',
      author_email='rteague@umich.edu',
      license='????',
      packages=find_packages(),
      include_package_data=True,
      install_requires=['scipy', 'numpy', 'matplotlib', 'celerite'],
      zip_safe=False
      )
