from setuptools import setup, find_packages

long_description = '''
'''

setup(
    name="cor",
    version="0.2",
    description="Algebraic Data Types et al.",
    long_description=long_description,
    url="https://github.com/deztructor/pycor",
    author="Denis Zalevskiy",
    author_email="denis@visfun.org",
    license='MIT',
    classifiers=[
        'Development Status :: 3 - Alpha',
        'Intended Audience :: Developers',
        'Topic :: Software Development :: Build Tools',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.6',
    ],
    keywords="adt contract types development",
    packages=find_packages(exclude=['tests', 'examples']),
    test_suite='tests',
    setup_requires=['pytest-runner'],
    tests_require=['pytest'],
)
