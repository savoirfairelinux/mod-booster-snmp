try:
    from setuptools import setup, find_packages
except ImportError:
    from distribute_setup import use_setuptools
    use_setuptools()
    from setuptools import setup, find_packages


setup(
    name='mod-snmpbooster',
    version="2.0~alpha",
    description='SNMP booster module for Shinken',
    author='Thibault Cohen',
    author_email='thibault.cohen@savoirfairelinux.com',
    url='https://github.com/savoirfairelinux/mod-booster-snmp',
    license='AGPLv3',
    install_requires=["redis",
                      "pysnmp",
                      "pyasn1",
                      "configobj",
                      ],
    packages=find_packages(),
    package_dir={'snmp_booster': 'shinken/modules/snmp_booster'},
    include_package_data=True,
#    namespace_packages=['shinken.modules.snmp_booster'],
    test_suite='nose.collector',
    entry_points="""module.tools.sbcm:main""",
)

