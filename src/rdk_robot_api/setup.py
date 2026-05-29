from setuptools import setup, find_packages
import os
from glob import glob

package_name = 'rdk_robot_api'

def package_files(directory):
    paths = []
    for (path, directories, filenames) in os.walk(directory):
        for filename in filenames:
            paths.append((os.path.join('share', package_name, path), [os.path.join(path, filename)]))
    return paths

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.launch.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
    ] + package_files('static'),
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ranger',
    maintainer_email='sglh666@gmail.com',
    description='FastAPI and Scheduler Web API bridge for RDK Robot',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'api_server = rdk_robot_api.main:main'
        ],
    },
)
