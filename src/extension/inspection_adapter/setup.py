from setuptools import setup

setup(
    name="inspection_adapter",
    version="0.1.0",
    packages=["inspection_adapter"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/inspection_adapter"]),
        ("share/inspection_adapter", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="young",
    maintainer_email="young@example.com",
    description="Versioned provider boundary for external inspection actions.",
    license="Apache-2.0",
    entry_points={"console_scripts": ["inspection_adapter = inspection_adapter.node:main"]},
)
