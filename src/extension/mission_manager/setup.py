from setuptools import setup


setup(
    name="mission_manager",
    version="0.1.0",
    packages=["mission_manager"],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/mission_manager"]),
        ("share/mission_manager", ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="young",
    maintainer_email="young@example.com",
    description="Robot-side persistent mission execution and status",
    license="Apache-2.0",
    entry_points={
        "console_scripts": [
            "mission_manager = mission_manager.node:main",
            "map_bundle_monitor = mission_manager.map_bundle:monitor_main",
            "map_bundle_manifest = mission_manager.map_bundle:manifest_main",
        ],
    },
)
