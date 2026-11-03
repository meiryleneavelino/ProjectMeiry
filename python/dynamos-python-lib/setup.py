from setuptools import setup, find_packages

setup(
    name='dynamos',
    version='0.1',
    packages=find_packages(),
    include_package_data=True,
    install_requires=[
        'grpcio==1.71.0',
        'google>=3.0.0',
        'grpcio-tools==1.71.0',
        'retrying>=1.3.4',
        'grpclib>=0.4.5',
        'protobuf==5.29.4',
        'opentelemetry-api==1.32.0',
        'opentelemetry-instrumentation>=0.53b0',
        'opentelemetry-instrumentation-grpc>=0.53b0',
        'opentelemetry-semantic-conventions==0.53b0',
        'opentelemetry-exporter-otlp==1.32.0',
        'opentelemetry-exporter-otlp-proto-common==1.32.0',
        'opentelemetry-exporter-otlp-proto-grpc==1.32.0',
        'opentelemetry-sdk==1.32.0',
    ],
    author='Jorrit S.',
    author_email='',
    description='Python lib to interface microservice to DYNAMOS',
    url='https://github.com/Javernus/DYNAMOS'
)
