"""Explicit OUTPUT gate opt-out for this regression suite.

EZ_NEST_OUTPUT_GATE_OPEN is honored only for a source checkout started in
dev mode. Frozen builds and the container image ignore it. Gate tests clear
both variables when they need the real connection check.
"""
import os

os.environ.setdefault('EZ_NEST_DEV', '1')
os.environ.setdefault('EZ_NEST_OUTPUT_GATE_OPEN', '1')
