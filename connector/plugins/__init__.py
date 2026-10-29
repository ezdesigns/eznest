"""Plug-ins. Each one turns a local source into allow-listed observations."""
from connector.plugins import eznest, inventory, onyx_joblog, summa_joblog

PARSERS = {
    'eznest': eznest,
    'onyx_joblog': onyx_joblog,
    'summa_joblog': summa_joblog,
    'inventory': inventory,
}
