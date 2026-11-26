"""Install the transport-independent WP5 interface package.
安装独立于传输层的 WP5 接口包。
"""

from setuptools import setup


setup(
    name='iir_interaction',
    version='0.1.0',
    packages=['iir_interaction'],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/iir_interaction']),
        ('share/iir_interaction', ['package.xml']),
    ],
    install_requires=['setuptools', 'aiohttp>=3.9,<4'],
    extras_require={'asr': ['numpy', 'sherpa-onnx']},
    zip_safe=True,
    maintainer='SuxinZhang',
    maintainer_email='170072732+zhanglove2003@users.noreply.github.com',
    description='WP5 audio ownership and voice interface contracts',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={'console_scripts': ['interaction_service = iir_interaction.service:main', 'interaction_asr = iir_interaction.asr:main', 'interaction_node = iir_interaction.ros_node:main']},
)
