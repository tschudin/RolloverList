#!/usr/bin/env python3

# prunableLog.py

# An append-only log with the possibility to prune old entries
# (c) Sep 2026 <christian.tschudin@unibas.ch>, MIT license

class PrunableLog:

    def __init__(self):
        self.content = []
        self.startSeq = 0

    def _dump(self, comment=None):
        print(f"Dump of log content (startSeq={self.startSeq}, "
              f"len={len(self.content)}): ", end='')
        print("" if comment == None else comment)
        seq = self.startSeq
        for e in self.content:
            print(f"  {seq}: {e}")
            seq += 1

    def __iter__(self):
        return (c for c in self.content)

    def __len__(self):
        return len(self.content)

    def __getitem__(self, seq):
        if seq < 0:
            seq += self.startSeq + len(self.content)
        return self.content[seq - self.startSeq]

    def getSeqRange(self): # returns lowest and highest sequence numbers
        return ( self.startSeq, self.startSeq + len(self.content) - 1 )

    def append(self, x):
        self.content.append(x)
        return self.startSeq + len(self.content) - 1

    def prune(self, up_to):
        cnt = up_to - self.startSeq
        self.content = self.content[cnt:]
        self.startSeq += cnt
        return len(self.content)

    pass

# ---------------------------------------------------------------------------

if __name__ == '__main__':

    pl = PrunableLog()

    for x in "abcdef":
        pl.append(x)

    pl.prune(2)
    print(f"Element with seq# 3 is {pl[3]}\n")

    pl._dump("after pruning")

# eof
