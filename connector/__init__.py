"""Shop Connector prototype.

One local program reads shop tools and, after pairing, POSTs a single
versioned event shape to OUTPUT. It does not change Ez Nest nesting, export,
or the shop installation. It is off until a plug-in is switched on.
"""

SCHEMA = 'shop-connector-event/1'
VERSION = '0.1.0'
