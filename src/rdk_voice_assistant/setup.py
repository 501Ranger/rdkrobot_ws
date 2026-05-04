import os
from glob import glob

from setuptools import find_packages, setup


package_name = 'rdk_voice_assistant'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'),
            glob(os.path.join('launch', '*launch.py'))),
        (os.path.join('share', package_name, 'config'),
            glob(os.path.join('config', '*.yaml'))),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='ranger',
    maintainer_email='ranger@todo.todo',
    description='Voice assistant bridge for text/voice commands and robot task interfaces.',
    license='TODO',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'voice_assistant_node = rdk_voice_assistant.voice_assistant_node:main',
            'rdk_asr_bridge_node = rdk_voice_assistant.rdk_asr_bridge_node:main',
            'rdk_tts_bridge_node = rdk_voice_assistant.rdk_tts_bridge_node:main',
            'local_stt_node = rdk_voice_assistant.local_stt_node:main',
            'local_tts_node = rdk_voice_assistant.local_tts_node:main',
            'llm_dialog_node = rdk_voice_assistant.llm_dialog_node:main',
        ],
    },
)
