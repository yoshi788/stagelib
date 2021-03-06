import os, sys, re, gc, io, csv, xlrd, json, zipfile
import shutil, subprocess, hashlib, contextlib
from subprocess import PIPE
from datetime import date
from string import punctuation
from cStringIO import StringIO
from collections import Counter, defaultdict
from functools import partial, wraps

from generic import *
from timeutils import utcnow

pd = None
isearch = partial(lambda x: re.compile(x, re.I).search)

def importpandas():
    global pd
    if not pd:
        import pandas as pd

def pathdeco(func):
    @wraps(func)
    def inner(path, *args, **kwds):
        return func(OSPath(path), *args, **kwds)
    return inner

def presence(exists = True):
    def decorator(func):
        @wraps(func)
        def inner(path, *args, **kwds):
            if os.path.exists() is exists:
                return func(str(path), *args, **kwds)
        return inner
    return decorator

if_exists = presence()
if_not_exists = presence(exists = False)

@contextlib.contextmanager
def fileopener(fh, mode = "rb", *args, **kwds):
    if isinstance(fh, (basestring, OSPath)):
        fh = io.open(str(fh), mode, **kwds)
    try:
        yield fh
    finally:
        fh.close()

def filehandler(mode = "rb"):
    def decorator(func):
        @wraps(func)
        def inner(fh, *args, **kwds):
            with fileopener(fh, mode = kwds.pop('mode', mode), **kwds) as fh:
                return func(fh, *args, **kwds)
        return inner
    return decorator

def is_zipfile(path):
    return zipfile.is_zipfile(path) and r'.xls' not in path

def filezip(newzipfile, path, mode = 'w', **kwds):
    with zipfile.ZipFile(newzipfile, mode = 'w', **kwds) as zf:
        zf.write(path, OSPath.basename(path))

filezip64 = partial(filezip,
    allowZip64 = True,
    compression = zipfile.ZIP_DEFLATED)

def fileunzip(zipname, outdir = '', switches = [], recursive = False, overwrite = 'n'):
    if not outdir:
        outdir = defaultdir(zipname)

    mkdir(outdir)
    cmd = 'unzip %s "%s" -d "%s"' % (' '.join(switches), zipname, outdir)
    p = subprocess.Popen(command, stdin = PIPE)
    p.communicate(input = overwrite)
    if recursive:
        for zn in Folder.listdir(outdir, recursive = True):
            if is_zipfile(zn) and zn != zipname:
                fileunzip(zn, switches = switches)
    return outdir

@pathdeco
def defaultdir(path):
    if path.isfile():
        return path.join(OSPath.dirname(path.abspath()), path.stem)
    return path.dirname()

@pathdeco
def mkpath(path, *args):
    return path.join(*args)

@pathdeco
def mktspath(path, datefmt = "%Y-%m-%d_%I.%M.%S", *args):
    return "{0}_{1}_.{2}".format(path.stem,
        utcnow().strftime(datefmt), path.ext)

def mkdir(dirname, *args):
    _dirname = mkpath(dirname, *args)
    if not OSPath.exists(_dirname):
        os.mkdir(_dirname)
    return _dirname

@pathdeco
def movepath(path, dest):
    try:
        shutil.move(path.path, mkdir(dest))
    except shutil.Error as e:
        path.error(e)

@filehandler()
def getmd5(fh):
    _md5 = hashlib.md5()
    while fh.tell() != OSPath.getsize(fh.name):
        _md5.update(fh.read(658760))
    return _md5.hexdigest()

@filehandler(mode = "rb")
def read(fh):
    return fh.read()

@filehandler(mode = 'wb')
def writedata(fh, data):
    fh.write(data)

@filehandler(mode = 'ab')
def appendData(fh, data):
    fh.write(data)

if_not_exists_write = if_not_exists(writedata)
if_exists_append = if_exists(appendData)

def chunkwriter(fh, data): ##for writing csv data in chunks
    if_exists_append(fh, data)
    if_not_exists_write(fh, data)

@filehandler(mode = 'r')
def from_json(fh):
    return json.loads(fh.read())

@if_exists
def from_json_if_exists(fh):
    return from_json(fh)

@filehandler(mode = 'w')
def to_json(fh, data, mode = 'w'):
    fh.write(json.dumps(data, sort_keys = True, indent = 4,))

def df2excel(output_file, **kwds):
    importpandas()
    xlwriter = pd.ExcelWriter(output_file)
    for sheet_name, df in kwds.items():
        df.to_excel(xlwriter,
            sheet_name = sheet_name,
            index = False,
            encoding = 'utf-8')
    xlwriter.save()

class OSPathMeta(type):
    _methods = attrdict(os.path)
    def __getattr__(cls, name):
        if name in cls._methods:
            return cls._methods[name]
        raise AttributeError

class OSPath(GenericBase):
    __metaclass__ = OSPathMeta
    is_key = isearch(r'((?<=get)(size|[a-z]time)|([a-z]+name|^ext$))')

    def __init__(self, path, setuplogging = False, *args, **kwds):
        self.path = path
        super(OSPath, self).__init__(path, setuplogging = setuplogging, *args, **kwds)
        grabfunctions(self, os.path, 'path')
        self.stem, self.ext = map(lambda x: x.strip('.'), self.splitext())

    def __str__(self):
        return self.path
    def __repr__(self):
        return "%s(%s)" % (self.__class__.__name__, self.path)

    @property
    def properties(self):
        if not hasattr(self, '_properties'):
            self._properties = {}
            for k, v in self.__dict__.items():
                if is_key(k):
                    k = is_key(k).group(1)
                    if isinstance(v, float):
                        v = date.fromtimestamp(v).strftime("%Y-%m-%d %I:%M:%S")
                    elif callable(v):
                        v = v()
                    self.__p.update({k : v})
        return self._properties

class File(OSPath):
    def __init__(self, path, mode = "rb", chunksize = 5 * (1024*1024), **kwds):
        super(File, self).__init__(path, mode = mode, chunksize = chunksize, **kwds)
        self.kwds = kwds

    def __iter__(self):
        with open(self.path, self.mode) as fh:
            for i, data in enumerate(chunker(fh, chunksize = self.chunksize)):
                self.chunkidx = i; yield data

    @staticmethod
    def guess_type(path, **kwds):
        try:
            return Excel(path, **kwds)
        except xlrd.XLRDError:
            return Csv(path, **kwds)

class TabularFile(File):
    def __init__(self, path, *args, **kwds):
        super(TabularFile, self).__init__(path, *args, **kwds)
        importpandas()

    def __call__(self, data, **kwds):
        if not hasattr(self, 'items'):
            self.items = []

        kwds = mergedicts(kwds, self.kwds, lineterminator = '\n')
        if 'converters' not in kwds:
            kwds['converters'] = {name : str for name in kwds['names']}

        if 'na_values' not in kwds:
            kwds['na_values'] = ['null']
        else:
            kwds['na_values'].append('null')

        self.items.append({
            'sample' : pd.read_csv(StringIO(data), **mergedicts(kwds, nrows = 50)),
            'data' : io.BytesIO(data),
            'kwds' : kwds
                })

    def __getitem__(self, val):
        if hasattr(self, 'items'):
            return self.items[val]
        raise IndexError

    @property
    def properties(self):
        __ = super(TabularFile, self).properties
        if hasattr(self, 'nrows'):
            __.update({'rows_original' : self.nrows})
        return __

class Csv(TabularFile):
    DELIMITERS = '|,\t;:'
    NON_FIELD = '(?=^(?:(?:\$)\d+(?:[-\/\.\s,]+|$)|[%s]|[\|,\t]+(?:\s+)?|$)$)' % punctuation
    IMPROPER = r'(.*?"),(?:[",]+)?((?:[\r\n]|$))'
    improper = isearch(IMPROPER)
    non_field = isearch(NON_FIELD)
    fix = partial(resub(IMPROPER), r'\1\2')

    def __init__(self, path, mode = "U", chunksize = 79650, **kwds):
        super(Csv, self).__init__(path, mode = mode, chunksize = chunksize, **kwds)
        self.fixcsv = Csv.improper(self.testraw)
        self.delimiter = self.sniff()

    @staticmethod
    def rowlengths(rows):
        for row in rows:
            for n in (0, -1):
                while row and not row[n]:
                    row.pop(n)
        return map(len, rows)

    @staticmethod
    def create_header(length = 10):
        return map(lambda x: "field.%s.of.%s" % (x[0], length),
            enumerate(xrange(1, length + 1), 1))

    @staticmethod
    def locate_header(rows):
        lens = Csv.rowlengths(rows)
        ml = max(lens)
        ix = lens.index(ml)
        for i, row in enumerate(rows[ix:], ix):
            if any(Csv.non_field(re.sub('\s+', ' ', str(x))) for x in row):
                continue
            return i + 1, row
        else:
            return ix, Csv.create_header(ml)

    @property
    def testraw(self):
        return self.head()

    @property
    def testrows(self):
        return self.reader(self.testraw)

    @property
    def rules(self):
        if not hasattr(self, '_header'):
            self._header = self.locate_header(self.testrows)
            
        skprows = self._header[0]
        if self.chunkidx > 0:
            skprows = 0

        return {delimiter = getattr(self, 'delimiter', self.sniff()),
                nrows = getattr(self, 'nrows', None),
                skiprows = skprows,
                names = self._header[1]}
        
    @filehandler()
    def head(self, n = 50):
        return Csv.fix(''.join(self.readline() for i in xrange(n)))

    def sniff(self):
        counts = filter(lambda x: x[0] in Csv.DELIMITERS,
            Counter(self.testraw).most_common())

        for k,v in counts:
            if k in Csv.DELIMITERS:
                return k
        raise csv.Error, "Delimiter undetermined."

    def reader(self, data):
        return [i for i in csv.reader(StringIO(data),
            delimiter = self.delimiter, quoting = 1)]

    def preprocess(self):
        self.nrows = 0
        self._header = self.locate_header(self.testrows)

        for i, data in enumerate(self):
            self.nrows += len(data)
            data = ''.join(data)
            if self.fixcsv:
                data = Csv.fix(data)

            if self.delimiter == '|':
                data = re.sub(r'\s+\|\s+', ' - ', data)

            self(data, **mergedicts(kwds, self.rules))
            gc.collect()
            yield kwds

class IncompleteExcelFile(Exception):
    def __init__(self):
        super(IncompleteExcelFile, self).__init__("This sheet contains exactly 65536 rows.  Data may be incomplete.")

class Excel(TabularFile):
    def __init__(self, path, mode = 'rb', **kwds):
        super(Excel, self).__init__(path, mode = mode, **kwds)
        self.wb = xlrd.open_workbook(self.path, on_demand = True)

    def __csvstring(self, rows):
        buf = StringIO()
        cw = csv.writer(buf, quoting = csv.QUOTE_ALL, lineterminator = '\n')
        cw.writerows(rows)
        return buf.getvalue()

    def reader(self, sheet):
        return [[x.encode('utf-8') if isinstance(x, unicode) else
                x for x in sheet.row_values(n)] for n in xrange(sheet.nrows)]

    def preprocess(self):
        self.nrows = sum(sheet.nrows for sheet in self.wb.sheets())
        for sheet in self.wb.sheets(): ###HERE
            if sheet.nrows >= 1:
                rows = self.reader(sheet)
                __ = Csv.locate_header(rows[0:50])

                kwds = {'skiprows' : __[0],
                        'names' :__[1],
                        'nrows' : sheet.nrows}

                self(self.__csvstring(rows), **kwds)  ##CULPRIT, skips columns
            elif sheet.nrows == 65536:
                raise IncompleteExcelFile
            yield kwds

class Folder(OSPath):
    def __init__(self, path, pattern = '', recursive = False, files_only = False, setuplogging = True, **kwds):
        self.search = lambda x, pattern = pattern: isearch(pattern)(x)
        if self.search(path, pattern = r'(?:\.|^$)'):
            path = os.getcwd()
        self.dupes = set()
        self.dist = set()
        self.recursive = recursive
        self.files_only = files_only
        importpandas()
        super(Folder, self).__init__(path, setuplogging = setuplogging)

    def __getitem__(self, n):
        if hasattr(self, '_%s__cache' % self.__class__.__name__):
            return list(self.__cache)[n]
        raise IndexError

    @classmethod
    def listdir(cls, dirname, **kwds):
        _ = cls(dirname, **kwds)
        if not kwds.get('recursive', _.recursive):
            return list(_)
        return (i for i in cls(dirname, **kwds))

    @classmethod
    def unzipfiles(cls, dirname, recursive_unzip = False, extractdir = 'unzipped', **kwds):
        for zipname in filter(is_zipfile, cls.listdir(dirname, **kwds)):
            fileunzip(zipname, recursive = recursive_unzip, outdir = extractdir)
        return extractdir
        
    @classmethod
    def table(cls, *args, **kwds):
        return pd.DataFrame([
            OSPath(path).properties for path in Folder.listdir(*args, **kwds)
                ])

    def deduplicate(self):
        __ = defaultdict(list)
        self.unzipfiles()
        self.recursive = True
        self.files_only = True
        for fname in self:
            if not is_zipfile(fname):
                __[getmd5(fname)].append(fname)
        for k, v in __.items():
            if len(v) > 1:
                self.info("Duplicate found: %s" % v[1])
                self.dupes.add(v[1])
            self.dist.add(v[0])
            yield v[0]

    def _walk(self):
        if not self.recursive:
            for path in (self.join(i) for i in os.listdir(self.path) if self.search(i)):
                yield path
        else:
            for root, dirs, files in os.walk(self.path):
                if not self.files_only:
                    files.extend(dirs)
                for fname in sorted(files):
                    path = mkpath(root, fname)
                    if not self.search(path):
                        continue
                    yield path

    def __iter__(self):
        for path in self._walk():
            yield path