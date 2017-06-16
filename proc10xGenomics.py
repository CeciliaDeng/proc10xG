#!/usr/bin/env python
"""
# Copyright 2017 Matt Settles
# Created June 8, 2017
"""
from optparse import OptionParser
import sys
import os
import time
import glob
import errno
from subprocess import Popen, PIPE, STDOUT
import string
from collections import Counter
import numpy


def median(lst):
    return numpy.median(numpy.array(lst))


def sp_gzip_read(file, bufsize=-1):
    p = Popen('gzip --decompress --to-stdout'.split() + [file], stdout=PIPE, stderr=STDOUT, bufsize=bufsize)
    return p.stdout


def sp_gzip_write(file, bufsize=-1):
    filep = open(file, 'wb')
    p = Popen('gzip', stdin=PIPE, stdout=filep, shell=True, bufsize=bufsize)
    return p.stdin


def make_sure_path_exists(path):
    """
    Try and create a path, if not error
    """
    if path != '':
        try:
            os.makedirs(path)
        except OSError as exception:
            if exception.errno != errno.EEXIST:
                raise
    return path


rcs = string.maketrans('TAGCtagc', 'ATCGATCG')


def revcomp(seq):
    return seq.translate(rcs)[::-1]


def rev(seq):
    return seq[::-1]


def seqToHash(seq):
    encoding = {'a': 0, 'c': 1, 'g': 2, 't': 3, 'A': 0, 'C': 1, 'G': 2, 'T': 3}
    result = 0
    i = 0
    while i < len(seq):
        result += encoding.get(seq[i]) * 4**i
        i += 1
    return result


def getHammingOne(seq):
    basedict = {
        'A': ['C', 'G', 'T'],
        'C': ['A', 'G', 'T'],
        'G': ['A', 'C', 'T'],
        'T': ['A', 'C', 'G'],
        'a': ['C', 'G', 'T'],
        'c': ['A', 'G', 'T'],
        'g': ['A', 'C', 'T'],
        't': ['A', 'C', 'G']}
    res = []
    i = 0
    while i < len(seq):
        for j in basedict.get(seq[i]):
            res.append(seq[:i] + j + seq[i + 1:])
        i += 1
    return [seqToHash(sequence) for sequence in res]


def infer_read_file_name(baseread, seakread):
    ''' Find other read filenames (ex. R1, R2, R3, R4) in the directory based on Read 1 filename '''
    basename = os.path.basename(baseread)
    path = os.path.dirname(os.path.realpath(baseread))
    testname = glob.glob(path + '/*' + os.path.splitext(baseread)[1])
    count = 0
    pos = -1
    read = []
    for name in testname:
        count = 0
        if os.path.basename(name) == basename:  # ignore the same file
            continue
        elif len(os.path.basename(name)) != len(basename):  # must be the same length
            continue
        else:
            for i, (ch1, ch2) in enumerate(zip(os.path.basename(name), basename)):  # calculate the hamming distance
                if ch1 != ch2 and ch2 == '1' and ch1 == seakread:
                    count += 1
                    pos = i
            if count == 1:
                read.append(path + '/' + basename[0:pos] + seakread + basename[pos + 1:])
                continue
    if len(read) == 1:
        return read[0]
    else:
        raise Exception("Error inferring read " + seakread + " from read 1, found " + str(len(read)) + " suitable matches.")


class TwoReadIlluminaRun:
    """
    Class to open/close and read a two read illumina sequencing run. Data is expected to be in
    fastq format (possibly gzipped)
    """
    def __init__(self, read1, read2, gbctrim, trim, profile, verbose):
        """
        Initialize a TwoReadIlluminaRun object with expandible paths (with glob) to the two
        sequencing read files. A vector of multiple files per read is allowed.
        """
        self.verbose = verbose
        self.gbctrim = gbctrim
        self.trim = trim
        self.profile = profile
        self.isOpen = False
        self.mcount = 0
        self.fread1 = []
        self.fread2 = []
        try:
            for fread in read1:
                self.fread1.extend(glob.glob(fread))
                if len(self.fread1) == 0 or not all(os.path.isfile(f) for f in self.fread1):
                    sys.stderr.write('ERROR:[TwoReadIlluminaRun] read1 file(s) not found\n')
                    raise Exception
            if read2 is None:
                for fread in self.fread1:
                    self.fread2.append(infer_read_file_name(fread, "2"))
            else:
                for fread in read2:
                    self.fread2.extend(glob.glob(fread))
                    if len(self.fread2) == 0 or not all(os.path.isfile(f) for f in self.fread2):
                        sys.stderr.write('ERROR:[TwoReadIlluminaRun] read2 file not found\n')
                        raise Exception
            if len(self.fread1) != len(self.fread2):
                sys.stderr.write('ERROR:[TwoReadIlluminaRun] Inconsistent number of files for each read\n')
                raise
        except Exception:
            raise
        # record the number of files per read
        self.numberoffiles = len(self.fread1)

    def open(self):
        """
        Open a OneReadIlluminaRun file set, if file ends in .gz, open will use gzip
        """
        if self.isOpen:
            self.close()
        if self.numberoffiles > 0:
            try:
                read1 = self.fread1.pop()
                if read1.split(".")[-1] == "gz":
                    self.R1 = sp_gzip_read(read1)
                else:
                    self.R1 = open(read1, 'r')
                read2 = self.fread2.pop()
                if read2.split(".")[-1] == "gz":
                    self.R2 = sp_gzip_read(read2)
                else:
                    self.R2 = open(read2, 'r')
            except Exception:
                sys.stderr.write('ERROR:[TwoReadIlluminaRun] cannot open input files\n')
                raise
            self.isOpen = True
            self.numberoffiles -= 1
            if self.verbose:
                sys.stderr.write("FILES\topening files:%s,%s\n" % (read1, read2))
            return 0
        else:
            return 1

    def close(self):
        """
        Close a TwoReadIlluminaRun file set
        """
        self.R1.close()
        self.R2.close()
        self.isOpen = False

    def count(self):
        """
        Provide the current count of reads read
        """
        return self.mcount

    def nfiles(self):
        """
        provide the number of files given
        """
        return self.numberoffiles

    def next(self, ncount=1):
        """
        Extract and store the next [count] reads into a TwoSequenceReadSet object.
        If the file object is not open, or if 'next' reaches the end of a file, it will
        attempt to open the file in the list, or gracefully exit
        """
        if not self.isOpen:
            try:
                if self.open() == 1:
                    sys.stderr.write('ERROR:[TwoReadIlluminaRun] ERROR Opening files for reading\n')
                    raise
            except Exception:
                raise
        reads = []
        i = 0
        while i < ncount:
            try:
                # pull in read 1
                status = 'UNKNOWN'
                id1 = self.R1.next().strip()
                seq1 = self.R1.next().strip()
                self.R1.next()  # *
                qual1 = self.R1.next().strip()
                assert(len(seq1) == len(qual1))
                if id1 == '' or seq1 == ''or qual1 == '':
                    self.close()
                    raise StopIteration
                # pull in read2
                id2 = self.R2.next().strip()
                seq2 = self.R2.next().strip()
                self.R2.next()  # *
                qual2 = self.R2.next().strip()
                assert(len(seq2) == len(qual2))
                if id2 == '' or seq2 == ''or qual2 == '':
                    self.close()
                    raise StopIteration
                # check to make sure the IDs match across all files
                assert(id1.split()[0] == id2.split()[0])
                # TODO: add in profiler
                # Pase our the info
                rid = id1.split()[0]
                rbc = (id1.split()[1]).split(':')[3]
                if rbc == '':
                    rbc = "1"
                gbc = seq1[0:self.gbctrim]
                gbcq = qual1[0:self.gbctrim]
                trim = seq1[self.gbctrim:self.gbctrim + self.trim]
                trimq = qual1[self.gbctrim:self.gbctrim + self.trim]
                seq1 = seq1[self.gbctrim + self.trim:]
                qual1 = qual1[self.gbctrim + self.trim:]
                fragment = {'id': rid,
                            'status': status,
                            'library_bc': rbc,
                            'gem_bc': gbc,
                            'sgem_bc': gbc,
                            'sgem_qual': gbcq,
                            'trim_seq': trim,
                            'trim_qual': trimq,
                            'read1_seq': seq1,
                            'read1_qual': qual1,
                            'read2_seq': seq2,
                            'read2_qual': qual2}
                reads.append(fragment)
                self.mcount += 1
            except StopIteration:
                if self.numberoffiles > 0:
                    try:
                        if self.open() == 1:
                            sys.stderr.write('ERROR:[TwoReadIlluminaRun] ERROR Opening files for reading\n')
                            raise
                    except Exception:
                        raise Exception
                    continue
                raise StopIteration
            except Exception:
                sys.stderr.write('ERROR:[TwoReadIlluminaRun] Error reading next read\n')
                raise
            i += 1
        if len(reads) == 1:
            return reads[0]
        else:
            return reads


class IlluminaTwoReadOutput:
    """
    Given Paired-end reads, output them to a paired files (possibly gzipped)
    """
    def __init__(self, output_prefix, uncompressed, interleaved):
        """
        Initialize an IlluminaTwoReadOutput object with output_prefix and whether or not
        output should be compressed with gzip [uncompressed True/False]
        """
        self.isOpen = False
        self.output_prefix = output_prefix
        self.interleaved = interleaved
        self.uncompressed = uncompressed
        self.mcount = 0

        if output_prefix == "stdout":
            self.interleaved = True
            self.uncompressed = True
        elif self.uncompressed is True:
            if os.path.isfile(self.output_prefix + "_R1_001.fastq"):
                sys.stderr.write('WARNING:[IlluminaTwoReadOutput] File with prefix: %s exists, DELETING\n' % self.output_prefix)
                try:
                    if self.interleaved:
                        os.remove(self.output_prefix + "_R1_001.fastq")
                    else:
                        os.remove(self.output_prefix + "_R1_001.fastq")
                        os.remove(self.output_prefix + "_R2_001.fastq")
                except Exception:
                    sys.stderr.write('WARNING:[IlluminaTwoReadOutput] Cannot delete file with prefix: %s\n' % self.output_prefix)
                    raise
        else:
            if os.path.isfile(self.output_prefix + "_R1_001.fastq.gz"):
                sys.stderr.write('WARNING:[IlluminaTwoReadOutput] File with prefix: %s exists, DELETING\n' % self.output_prefix)
                try:
                    if self.interleaved:
                        os.remove(self.output_prefix + "_R1_001.fastq.gz")
                    else:
                        os.remove(self.output_prefix + "_R1_001.fastq.gz")
                        os.remove(self.output_prefix + "_R2_001.fastq.gz")
                except Exception:
                    sys.stderr.write('WARNING:[IlluminaTwoReadOutput] Cannot delete file with prefix: %s\n' % self.output_prefix)
                    raise

    def open(self):
        """
        Open the two read files for writing, appending _R1.fastq and _R2.fastq to the output_prefix.
        Create directories as needed.
        """
        if self.isOpen:
            self.close()
        try:
            if self.output_prefix == "stdout":
                self.R1f = sys.stdout
            else:
                make_sure_path_exists(os.path.dirname(self.output_prefix))
                if self.uncompressed is True:
                    self.R1f = open(self.output_prefix + '_R1_001.fastq', 'a')
                    if not self.interleaved:
                        self.R2f = open(self.output_prefix + '_R2_001.fastq', 'a')
                else:
                    self.R1f = sp_gzip_write(self.output_prefix + '_R1_001.fastq.gz', 'ab')
                    if not self.interleaved:
                        self.R2f = sp_gzip_write(self.output_prefix + '_R2_001.fastq.gz', 'ab')
        except Exception:
            sys.stderr.write('ERROR:[IlluminaTwoReadOutput] Cannot write reads to file with prefix: %s\n' % self.output_prefix)
            raise
        self.isOpen = True
        return 0

    def close(self):
        """
        Close an IlluminaTwoReadOutput file set
        """
        try:
            self.R1f.close()
            if not self.interleaved:
                self.R2f.close()
        except Exception:
            raise
        self.isOpen = False
        sys.stderr.write("FILES\tWrote %i reads to output\n" % self.mcount)

    def count(self):
        """
        Provide the current read count for the file output
        """
        return self.mcount

    def writePairedFastq(self, fragment):
        newid = '@' + (':').join([fragment['gem_bc'], fragment['id'][1:]])
        # read 1
        self.R1f.write((' ').join([newid, (':').join(['1', 'N', '0', fragment['status'], fragment['library_bc'], fragment['sgem_bc'], fragment['sgem_qual'], fragment['trim_seq'], fragment['trim_qual']])]) + '\n')
        self.R1f.write(fragment['read1_seq'] + '\n')
        self.R1f.write('+\n')
        self.R1f.write(fragment['read1_qual'] + '\n')
        # read 2
        self.R2f.write((' ').join([newid, (':').join(['2', 'N', '0', fragment['status'], fragment['library_bc'], fragment['sgem_bc'], fragment['sgem_qual'], fragment['trim_seq'], fragment['trim_qual']])]) + '\n')
        self.R2f.write(fragment['read2_seq'] + '\n')
        self.R2f.write('+\n')
        self.R2f.write(fragment['read2_qual'] + '\n')
        self.mcount += 1

    def writeFastqInterleaved(self, fragment):
        newid = '@' + (':').join([fragment['gem_bc'], fragment['id'][1:]])
        # read 1
        self.R1f.write((' ').join([newid, (':').join(['1', 'N', '0', fragment['status'], fragment['library_bc'], fragment['sgem_bc'], fragment['sgem_qual'], fragment['trim_seq'], fragment['trim_qual']])]) + '\n')
        self.R1f.write(fragment['read1_seq'] + '\n')
        self.R1f.write('+\n')
        self.R1f.write(fragment['read1_qual'] + '\n')
        # read 2
        self.R1f.write((' ').join([newid, (':').join(['2', 'N', '0', fragment['status'], fragment['library_bc'], fragment['sgem_bc'], fragment['sgem_qual'], fragment['trim_seq'], fragment['trim_qual']])]) + '\n')
        self.R1f.write(fragment['read2_seq'] + '\n')
        self.R1f.write('+\n')
        self.R1f.write(fragment['read2_qual'] + '\n')

    def writeRead(self, fragment):
        """
        Write the paired read in the queue to the output files
        """
        if (len(fragment) == 0):
            pass
        else:
            if not self.isOpen:
                try:
                    if self.open() == 1:
                        sys.stderr.write('ERROR:[IlluminaTwoReadOutput] ERROR Opening files for writing\n')
                        raise
                except Exception:
                    raise
            try:
                if self.interleaved:
                    self.writeFastqInterleaved(fragment)
                else:
                    self.writePairedFastq(fragment)
            except Exception:
                sys.stderr.write('ERROR:[IlluminaTwoReadOutput] Cannot write reads to file with prefix: %s\n' % self.output_prefix)
                raise


def main(read1, read2, output_dir, output_all, interleaved, profile, bctrim, trim, nogzip, verbose):
    # Set up the global variables
    global read_count
    global stime

    barcode_match = 0
    barcode_1mismatch = 0
    barcode_ambiguous = 0
    barcode_unknown = 0

    gbcDict = {}
    gbcCounter = Counter()

    # open output files
    output = IlluminaTwoReadOutput(output_dir, nogzip, interleaved)

    # Process read inputs:
    iterator = TwoReadIlluminaRun(read1, read2, bctrim, trim, profile, verbose)

    # Load the gem barcode dictionary with the whitelist
    with open('barcodes/4M-with-alts-february-2016.txt', 'r') as f:
        for bc_sequence in f:
            gbcDict[seqToHash(bc_sequence.strip())] = bc_sequence.strip()

    try:
        while 1:
            fragment = iterator.next()
            read_count += 1
            if seqToHash(fragment['gem_bc']) in gbcDict:  # barcode matches whitelist
                gbcCounter[seqToHash(fragment['gem_bc'])] += 1
                barcode_match += 1
                fragment['status'] = "GOOD"
            else:
                hamming = getHammingOne(fragment['gem_bc'])
                hamming_test = [ham in gbcDict for ham in hamming]
                if sum(hamming_test) == 0:  # greater than 1 hamming distance
                    barcode_unknown += 1
                    if not output_all:
                        continue
                elif sum(hamming_test) == 1:  # single hit hamming distance of 1
                    index = hamming[[i for i, x in enumerate(hamming_test) if x][0]]
                    fragment['gem_bc'] = gbcDict[index]
                    gbcCounter[index] += 1
                    barcode_1mismatch += 1
                    fragment['status'] = "MISMATCH1"
                else:  # multihit hamming distance of 1
                    barcode_ambiguous += 1
                    fragment['status'] = "AMBIGUOUS"
                    if not output_all:
                        continue

            output.writeRead(fragment)

            if read_count % 250000 == 0 and verbose:
                sys.stderr.write("READS\treads analyzed:%i|reads/sec:%i|barcodes:%i|median_reads/barcode:%.2f\n" % (read_count, round(read_count / (time.time() - stime), 0), len(gbcCounter), median(gbcCounter.values())))

    except StopIteration:
        with open(output_dir + '_barcodes.txt', 'w') as f:
            [f.write('{0}:{1}\n'.format(gbcDict[key], value)) for key, value in gbcCounter.items()]
        output.close()

        if verbose:
            sys.stderr.write("BARCODE\tmatch: %i\n" % barcode_match)
            sys.stderr.write("BARCODE\tmismatch1: %i\n" % barcode_1mismatch)
            sys.stderr.write("BARCODE\tambiguous: %i\n" % barcode_ambiguous)
            sys.stderr.write("BARCODE\tunknown: %i\n" % barcode_unknown)
            sys.stderr.write("Finally, reads analyzed: %i | reads/sec: %i | barcodes: %i | reads/barcode: %f\n" % (read_count, round(read_count / (time.time() - stime), 0), len(gbcCounter), median(gbcCounter.values())))
        pass


#####################################
# Parse options and setup #
usage = "usage %prog -o [output file prefix (path + name)] -(pbtg) --quite -1 [read1] -2 [read2] -3 [read3]"
usage += "%prog will process read file produced by 10x genomics and do some stuff"
parser = OptionParser(usage=usage, version="%prog 0.0.1")

parser.add_option('-o', '--output', help="Directory + prefix to output reads, if stdout",
                  action="store", type="str", dest="output_dir", default="stdout")

parser.add_option('-a', '--all', help="output all reads, not just those with valid gem barcode, STATUS will be UNKNOWN, or AMBIGUOUS",
                  action="store_true", dest="output_all", default=False)

parser.add_option('-i', '', help="output in interleaved format, if -o stdout, interleaved will be chosen automatically",
                  action="store_true", dest="interleaved", default=False)

parser.add_option('-p', '', help="profile the reads and barcodes, FUTURE",
                  action="store_true", dest="profile", default=False)

parser.add_option('-b', '--bctrim', help="trim gem barcode",
                  action="store", type="int", dest="bctrim", default=16)

parser.add_option('-t', '--trim', help="trim addional bases after the gem barcode",
                  action="store", type="int", dest="trim", default=7)

parser.add_option('-1', '--read1', metavar="read1", dest='read1', help='read1 of a pair, multiple files can be specified separated by comma',
                  action='store', type=str, nargs=1)

parser.add_option('-2', '--read2', metavar="read2", dest='read2', help='read2 of a pair, multiple files can be specified separated by comma',
                  action='store', type=str, nargs=1)

parser.add_option('-g', '--nogzip', help="do not gzip the output, ignored if output is stdout",
                  action="store_false", dest="nogzip", default=True)

parser.add_option('--quite', help="turn off verbose output",
                  action="store_false", dest="verbose", default=True)

(options, args) = parser.parse_args()

output_dir = options.output_dir
profile = options.profile
bctrim = options.bctrim
trim = options.trim
nogzip = options.nogzip
output_all = options.output_all
interleaved = options.interleaved

infile1 = options.read1
if infile1 is None:
    sys.stderr.write("Read file 1 is missing\n")
    sys.exit(1)
infile1 = infile1.split(',')
infile2 = options.read2
if infile2 is None:
    sys.stderr.write("Read file 2 is missing\n")
    sys.exit(1)
infile2 = infile2.split(',')

verbose = options.verbose

# need to check, can write to output folder

# global variables
read_count = 0

stime = time.time()

main(infile1, infile2, output_dir, output_all, interleaved, profile, bctrim, trim, nogzip, verbose)

sys.exit(0)