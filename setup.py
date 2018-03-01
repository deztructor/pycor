from setuptools import setup, find_packages
setup(
    name="cor",
    version="0.1",
    packages=find_packages(),
    test_suite='tests',
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
)
