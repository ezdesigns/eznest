"""Bound PDF working memory without turning detailed artwork into Python lists.

The tokenizer delegates PDF objects and inline images to pinned pypdf. Unchanged
operators retain their original bytes; only cut/layer edits are serialized.
"""
import ctypes
import functools
import io
import mmap
import os
import re

from pypdf import apply_configuration, get_configuration
from pypdf.generic import ContentStream, NameObject, read_object
from pypdf.generic._utils import StreamParsingBudget
from pypdf._utils import read_non_whitespace, read_until_regex
from pypdf.errors import PdfReadError


class MappedPdf(mmap.mmap):
    # PDFium's file callback requires readinto as well as seek/read/tell.
    def readinto(self, buffer):
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def available_memory():
    if os.name == 'nt':
        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in
                ('total', 'available', 'page_total', 'page_available', 'virtual', 'virtual_available', 'extended')]
        memory = Memory(); memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            return memory.available
    else:
        try:
            return os.sysconf('SC_AVPHYS_PAGES') * os.sysconf('SC_PAGE_SIZE')
        except (ValueError, OSError, AttributeError):
            pass
    return 900_000_000  # Conservative fallback, not unlimited decoding.


def print_pdf_context(function):
    @functools.wraps(function)
    def wrapped(*args, **kwargs):
        # Leave headroom for PDFium, geometry, source images and other shop apps.
        budget = max(1, min(512_000_000, available_memory() // 12))
        with apply_configuration(maximum_declared_stream_length=budget,
                                 zlib_maximum_output_length=budget,
                                 array_based_stream_maximum_output_length=budget,
                                 stream_decoding_work_maximum_length=budget * 4):
            return function(*args, **kwargs)
    return wrapped


# Illustrator emits most path coordinates one operator per line. This fast path
# accepts only simple numbers and known fixed-arity operators; everything else
# uses the PDF tokenizer (strings, arrays, dictionaries, comments, inline images).
_NUMBER = rb'[+-]?(?:\d+\.?\d*|\.\d+)'
_SIMPLE = re.compile(rb'((?:' + _NUMBER + rb'[ \t]+)*)([A-Za-z*]+)[ \t]*\r?\n')
_LINE_END = re.compile(rb'[\r\n]')
_ARITY = {b'm':2, b'l':2, b'c':6, b'v':4, b'y':4, b're':4,
          b'cm':6, b'w':1, b'J':1, b'j':1, b'M':1, b'g':1, b'G':1,
          b'rg':3, b'RG':3, b'k':4, b'K':4,
          **{op:0 for op in (b'q',b'Q',b'h',b'S',b's',b'f',b'F',b'f*',b'B',b'B*',b'b',b'b*',b'n',b'W',b'W*')}}


def operations(content):
    """Yield one operation plus its original syntax, never a whole-page list."""
    data = content.get_data()
    stream = io.BytesIO(data)
    while stream.tell() < len(data):
        start = stream.tell()
        match = _SIMPLE.match(data, start)
        if match and match[2] in _ARITY:
            values = match[1].split()
            if len(values) == _ARITY[match[2]]:
                stream.seek(match.end())
                yield [float(v) for v in values], match[2], data[start:match.end()]
                continue
        operands = []
        budget = StreamParsingBudget(get_configuration().stream_parsing_work_maximum_count)
        while True:
            peek = read_non_whitespace(stream)
            if not peek:
                if operands:
                    raise PdfReadError('Incomplete PDF operator.')
                return
            stream.seek(-1, 1)
            if peek.isalpha() or peek in (b"'", b'"'):
                op = read_until_regex(stream=stream, regex=NameObject.delimiter_pattern,
                                      length=content._OPERATOR_LENGTH_LIMIT)
                if op == b'BI':
                    if operands:
                        raise PdfReadError('Invalid inline image operands.')
                    operands = content._read_inline_image(stream, parsing_budget=budget)
                    op = b'INLINE IMAGE'
                yield operands, op, data[start:stream.tell()] + b'\n'
                break
            if peek == b'%':
                end = _LINE_END.search(data, stream.tell())
                stream.seek(end.end() if end else len(data))
                continue
            budget.remaining_budget -= 1
            if budget.remaining_budget < 0:
                raise PdfReadError('PDF operator has too many operands.')
            operands.append(read_object(stream, None, content.forced_encoding, parsing_budget=budget))


class OperationOutput:
    """Keep only the current path pending, so removed cuts can be discarded."""
    def __init__(self, writer):
        self.writer = writer
        self.body = io.BytesIO()
        self.pending = []
        self.original = None

    def append(self, item):
        operands, op = item
        if self.original and operands is self.original[0] and op == self.original[1]:
            raw = self.original[2]
        else:
            content = ContentStream(None, self.writer)
            content.operations = [item]
            raw = content.get_data()
        self.pending.append((op, raw))

    def extend(self, items):
        for item in items:
            self.append(item)

    def finish_path(self, remove=False):
        path_ops = (b'm',b'l',b'c',b'v',b'y',b're',b'h')
        for op, raw in self.pending:
            if not remove or op not in path_ops:
                self.body.write(raw)
        self.pending.clear()

    def get_data(self):
        self.finish_path()
        return self.body.getvalue()

