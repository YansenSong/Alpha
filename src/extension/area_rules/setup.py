from setuptools import setup


setup(
    name="area_rules",
    version="0.1.0",
    packages=["area_rules"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/area_rules"]),
        ("share/area_rules", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="young",
    maintainer_email="young@example.com",
    description="Persistent map rules and robot-side navigation constraints",
    license="Apache-2.0",
    entry_points={"console_scripts": ["area_rules = area_rules.node:main"]},
)
