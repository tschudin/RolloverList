#!/usr/bin/env python3

# roloList.py

# A rollover list (RoloLIST)
# (mutable list stored in a prunable but otherwise immutable append-only log)

# (c) Sep 2026 <christian.tschudin@unibas.ch>, MIT license


import prunableLog as pl

# ---------------------------------------------------------------------------

class RoloLIST:

    def __init__(self, log, wire=None):  # 'log' must be a prunable append-only log
        self.log = log
        self.dll = []         # dbl linked list of records with [val,prev,next]
        self.head_seq = None  # log seq# where first DLL element is stored
        self.tail_seq = None  # log seq# where last DLL element is stored
        self.wire = wire      # FIXME: implement wire bit encoding/decoding

        self.len = 0

        if len(log) > 0:
            self._load_from_log(log)

    def _dump(self, comment = ""):
        print(f"Dump of list {comment}")
        print(f"  head_seq={self.head_seq} tail_seq={self.tail_seq}, len={self.len}")
        print(f"  dll = {self.dll}")
        print(f"  \x1b[32mlist = {self.get_list()}\x1b[0m")

    def _load_from_log(self, log):
        if len(log) == 0:
            return

        # the log only stores 'prev' pointers: read them in a first pass
        self.dll = [[None,None,None] for i in range(len(log))]
        for seq,e in enumerate(log):
            for op in e:
                # don't load values yet, we do it during the reverse scan
                # if op[0] == 'v':
                #     self.dll[seq][0] = e[0][1]
                if op[0] == 'l':
                    ndx = op[1] - self.log.startSeq
                    if ndx >= 0: # and op[1] - self.log.startSeq >= 0:
                        self.dll[ndx][1] = op[2]
                elif op[0] == 't': # set tail
                    self.tail_seq = op[1]

        # now we have to populate the 'next' pointers. In this reverse pass
        # (from tail to head) we also update the list's len and read the values
        seq = self.tail_seq
        next = None
        while seq != None:
            self.len += 1
            ndx = seq - self.log.startSeq
            self.dll[ndx][0] = self.log[seq][0][1]
            self.dll[ndx][2] = next
            next = seq
            seq = self.dll[ndx][1]
        self.head_seq = next

        # note: unlinked elements have the first dll component set to None, can be pruned

    def _emit(self, ops):
        return self.log.append(ops)

    def _ndx2ndx(self, ndx): # convert roloLIST index to internal dll index by traversal
        if ndx < 0:
            ndx = self.len + ndx
        if ndx >= self.len:
            raise IndexError
        if ndx > self.len//2:
            seq = self.tail_seq
            ndx = self.len - 1 - ndx
            while ndx > 0:
                ndx -= 1
                seq = self.dll[self._seq2ndx(seq)][1]
        else:
            seq = self.head_seq
            while ndx > 0:
                ndx -= 1
                seq = self.dll[self._seq2ndx(seq)][2]
        return self._seq2ndx(seq)
        
    def _seq2ndx(self, seq):
        if seq == None:
            return None
        return seq - self.log.startSeq

    def _prune(self):
        cnt = 0
        for e in self.dll: # search first entry that has a value defined
            if e != None and e[0] != None:
                break
            cnt += 1
        self.log.prune(self.log.startSeq + cnt)
        self.dll = self.dll[cnt:]

    def _rollover(self):
        if self.len == 0:
            return
        ndx = 0  # oldest element in our dll
        val = self.dll[ndx][0]
        assert val != None
        new_seq = self.log.getSeqRange()[1] + 1

        ops = [ ('v',val) ]
        self.dll.append( [val, self.dll[ndx][1], self.dll[ndx][2]] )
        if self.dll[ndx][1] != None:
            ops.append( ('l', new_seq, self.dll[ndx][1]) )
            self.dll[self._seq2ndx(self.dll[ndx][1])][2] = new_seq
        if self.dll[ndx][2] != None:
            ops.append( ('l', self.dll[ndx][2], new_seq) )
            self.dll[self._seq2ndx(self.dll[ndx][2])][1] = new_seq
        if self._seq2ndx(self.head_seq) == ndx:
            self.head_seq = new_seq
        if self._seq2ndx(self.tail_seq) == ndx:
            ops.append( ('t', new_seq) )
            self.tail_seq = new_seq
        self._emit(ops)
        self.dll[ndx][0] = None

    # --------------------------------------------------
    
    def __len__(self):               # so that we can use  len(LIST)
        return self.len

    class _iterHelper:
        def __init__(self, dll, delta, ptr):
            self.dll = dll
            self.delta = delta
            self.ptr = ptr

        def __iter__(self):
            return self

        def __next__(self):
            if self.ptr == None:
                raise StopIteration
            else:
                ptr = self.ptr
                e = self.dll[ptr - self.delta]
                self.ptr = e[2]
            return e[0]

    def __iter__(self):               # so that list comprehension works
        return self._iterHelper(self.dll, self.log.startSeq, self.head_seq)

    def __getitem__(self, ndx):       # so that we can use  var = LIST[ndx]
        return self.dll[self._ndx2ndx(ndx)][0]

    def __setitem__(self, ndx, val):  # so that we can use  LIST[ndx] = val
        ndx = self._ndx2ndx(ndx)      # ndx is now relative to self.dll
        new_seq = self.log.getSeqRange()[1] + 1
        if self.len == 1:
            self._emit( ( ('v',val),
                          ('t',new_seq) ) )
            assert ndx == 0, print(f"ndx not zero, ndx={ndx}, dll={self.dll}")
            self.dll.append( [val, None, None] )
            self.head_seq = self.tail_seq = new_seq
            self.dll[ndx][0] = None
            self._prune()
            return
        # append new value to the log, splice the element into the linked list
        ops = [ ('v',val) ]
        self.dll.append( [val, self.dll[ndx][1], self.dll[ndx][2]] )
        if self.dll[ndx][1] != None:
            ops.append( ('l', new_seq, self.dll[ndx][1]) )
            self.dll[self._seq2ndx(self.dll[ndx][1])][2] = new_seq
        if self.dll[ndx][2] != None:
            ops.append( ('l', self.dll[ndx][2], new_seq) )
            self.dll[self._seq2ndx(self.dll[ndx][2])][1] = new_seq
        if self._seq2ndx(self.head_seq) == ndx:
            self.head_seq = new_seq
        if self._seq2ndx(self.tail_seq) == ndx:
            ops.append( ('t', new_seq) )
            self.tail_seq = new_seq
        self._emit(ops)
        self.dll[ndx][0] = None # mark for future GC/prune
        ops = []

        if ndx != 0:
            self._rollover()
        self._prune()

    def __delitem__(self, ndx):  # so that we can do  del LIST[ndx]
        if ndx < 0:
            ndx = self.len + ndx
        if ndx >= self.len: # this includes an empty list
            raise IndexError

        assert self.dll[0] != None

        if self.len == 1:
            for e in self.dll:
                if e != None:
                    e[0] = None
            self.head_seq = self.tail_seq = None
            self.len = 0
            return self._prune()
        # from here on we have at least two elements

        # find index of oldest log entry (to be moved to the front)
        oldest_val = None
        oldest_ndx = 0
        for e in self.dll:
            if e != None and e[0] != None:
                oldest_val = e[0]
                break
            oldest_ndx += 1

        # find element to be evicted
        ndx = self.len - 1 - ndx
        seq = self.tail_seq
        while ndx > 0:
            ndx -= 1
            seq = self.dll[self._seq2ndx(seq)][1]
        ndx = self._seq2ndx(seq)  # ndx now relative to self.dll

        ops = [] # collect operations on the prev-links, to be stored in the log

        if self._seq2ndx(self.head_seq) != ndx: # no change necessary
            new_head_seq = self.head_seq
        else: #  we have at least two elements, hence just follow link
            new_head_seq = self.dll[ndx][2]
        if self._seq2ndx(self.tail_seq) != ndx: # no change necessary
            new_tail_seq = self.tail_seq
        else: #  we have at least two elements, hence just follow link
            new_tail_seq = self.dll[ndx][1]

        # Is the oldest log entry, by chance, the element to be removed?
        if oldest_ndx == ndx: # not need to roll over, will be removed automatically
            oldest_val = None
        else: # move oldest entry to front of log
            new_seq = len(self.dll) + self.log.startSeq
            ops.append( ('v', oldest_val) )
            ops.append( ['l', new_seq, self.dll[oldest_ndx][1]]  )
            self.dll.append( [oldest_val,
                              self.dll[oldest_ndx][1],
                              self.dll[oldest_ndx][2]] )

            if self.dll[oldest_ndx][2] != None:
                ops.append( ['l', self.dll[oldest_ndx][2], new_seq] )
                self.dll[self._seq2ndx(self.dll[oldest_ndx][2])][1] = new_seq
            if self.dll[oldest_ndx][1] != None:
                self.dll[self._seq2ndx(self.dll[oldest_ndx][1])][2] = new_seq
            self.dll[oldest_ndx][0] = None  # tagged for GC/prunable

            if self._seq2ndx(new_head_seq) == oldest_ndx:
                new_head_seq = new_seq
            if self._seq2ndx(new_tail_seq) == oldest_ndx:
                new_tail_seq = new_seq

        # unlink element to be removed
        if self.dll[ndx][2] != None:
            ops.append( ['l', self.dll[ndx][2], self.dll[ndx][1]] )
            if oldest_ndx == ndx: # keep dll synchronized with log
                self.dll.append(None)
            self.dll[self._seq2ndx(self.dll[ndx][2])][1] = self.dll[ndx][1]
        if self.dll[ndx][1] != None:
            self.dll[self._seq2ndx(self.dll[ndx][1])][2] = self.dll[ndx][2]

        if new_head_seq != self.head_seq:
            self.head_seq = new_head_seq
        if new_tail_seq != self.tail_seq:
            ops.append( ('t', new_tail_seq) )
            self.tail_seq = new_tail_seq
            if oldest_ndx == ndx: 
                self.dll.append(None) # keep dll synchronized with log

        if len(ops) > 0:
            assert len(ops) <= 4, print(f"during del: ops={ops}, newseq={new_seq}")
            self._emit(ops)
        self.dll[ndx][0] = None  # tagged for GC/prunable
        self.len -= 1

        self._prune()

    # --------------------------------------------------

    def get_list(self): # for debugging/comparison purposes
        seq = self.tail_seq
        a = []
        while seq != None:
            e = self.dll[self._seq2ndx(seq)]
            a.append(e[0])
            seq = e[1] # this is the 'prev' field
        a.reverse()
        return a
    
    def append(self, val):      # same functionality as for Python lists
        new_seq = self.log.getSeqRange()[1] + 1
        if self.tail_seq == None:
            self._emit( ( ('v',val),
                          ('t',new_seq) ) )
            self.head_seq = new_seq
        else:
            self._emit( ( ('v',val),
                          ('l',new_seq,self.tail_seq),
                          ('t',new_seq) ) )
            self.dll[self._seq2ndx(self.tail_seq)][2] = new_seq # update 'next'
        self.dll.append([val,self.tail_seq,None])
        self.tail_seq = new_seq
        self.len += 1

    def insert(self, ndx, val): # same functionality as for Python lists
        if ndx < 0:
            ndx = self.len + ndx
        if ndx < 0 or ndx > self.len:
            raise IndexError

        if ndx == self.len:
            return self.append(val)

        new_seq = self.log.getSeqRange()[1] + 1  # position/address of new ele in the log
        ndx = self._ndx2ndx(ndx)                 # ndx is now relative to self.dll

        ops = [ ('v',val) ]
        if self.dll[ndx][1] != None:
            ops.append( ('l',new_seq,self.dll[ndx][1]) )
            self.dll[self._seq2ndx(self.dll[ndx][1])][2] = new_seq
        else:
            self.head_seq = new_seq
        ops.append( ('l',ndx + self.log.startSeq, new_seq) )
        self.dll.append([val, self.dll[ndx][1], ndx + self.log.startSeq])
        self.dll[ndx][1] = new_seq

        self._emit(ops)
        self.len += 1

    def clear(self):          # same functionality as in Python (removes all elements)
        self.log.prune(self.log.startSeq + len(self.log))
        self.head_seq = self.tail_seq = None
        self.dll = []
        self.len = 0

    def tidy(self):
        while len(self.log.content) != self.len:
            self._rollover()
            self._prune()

    pass

# ---------------------------------------------------------------------------

if __name__ == '__main__':

    import os
    import sys
    from traceback import TracebackException


    def verify_reload(lst1, comment):
        print(f"\n\x1b[32m** after {comment} **\x1b[0m\n")
        lst1.log._dump()
        lst1._dump("lst1")
        lst2 = RoloLIST(lst1.log) # load from log
        try:
            assert len(lst1) == len(lst2)
            assert lst1.head_seq == lst2.head_seq
            assert lst1.tail_seq == lst2.tail_seq
        except:
            print(f"\n** list mismatch: "
                  f"{(len(lst1),lst1.head_seq,lst1.tail_seq)}!="
                  f"{(len(lst2),lst2.head_seq,lst2.tail_seq)}")
            lst2.log._dump()
            lst2._dump("lst2")
            sys.exit(-1)
        for i in range(len(lst1)):
            try:
                assert lst1[i] == lst2[i]
            except:
                print(f"\n** list mismatch, startSeq={lst2.log.startSeq}")
                lst2.log._dump()
                lst2._dump("ra")
                sys.exit(-1)

    RL = RoloLIST( pl.PrunableLog() )

    RL.append('1')
    RL.append('2')
    RL.append('3')
    verify_reload(RL, "init")

    RL.insert(0,'0.5')
    verify_reload(RL, "insert '0.5' at 0")

    RL.insert(4,'3.5')
    verify_reload(RL, "insert '3.5' at 4")

    RL.insert(2,'1.5')
    verify_reload(RL, "insert '1.5' at 2")

    del RL[0]
    verify_reload(RL, "del #0")

    RL[2] = 99
    verify_reload(RL, "set [2] to 99")

    del RL[4]
    verify_reload(RL, "del #4")

    del RL[2]
    verify_reload(RL, "del #1")
    
    del RL[1]
    verify_reload(RL, "del #1")
    
    del RL[0]
    verify_reload(RL, "del #0")
    
    RL.clear()
    verify_reload(RL, "clear")
    
    RL.insert(0, "new 1")
    verify_reload(RL, "insert 'new 1' at 0")
    
    RL.insert(0, "new 0.5")
    verify_reload(RL, "insert 'new 0.5' at 0")
    
    del RL[1]
    verify_reload(RL, "del #1")

    
    RL.clear()
    print(f"\nApplying 1000 random list operations")
    print(f"  -> {[x for x in RL]}")
    for i in range(1000):
        l = len(RL)
        try:
            coin = os.urandom(1)[0] % 3
            if l == 0 or coin == 0:
                ndx = os.urandom(1)[0] % (l+1)
                v = os.urandom(3).hex()
                action = f"insert {v} at {ndx}"
                RL.insert(ndx, v)
            else:
                ndx = os.urandom(1)[0] % l
                if coin == 1:
                    action = f"del at {ndx}"
                    del RL[ndx]
                else:
                    v = os.urandom(3).hex()
                    action = f"set element {ndx} to {v}"
                    RL[ndx] = v

            # RL.tidy()

            print(f"  action #{i} was: {action}, len={len(RL)}, log_len={len(RL.log)}")
            print(f"  -> {[x for x in RL]}")

            assert RL.get_list() == [x for x in RL]

        except Exception as e:
            print(f"\nException '{e}'\n")
            TracebackException.from_exception(e, limit=-4).print()
            print(f"action={action}")
            RL.log._dump()
            RL._dump()
            break

    print("\nend of demo")

# eof
