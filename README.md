# Rollover LISTs and SETs (RoloLIST and RoloSET)

How can we publish a mutable data structure via an immutable
storage stream such that the stream can always be pruned?

This question emerges in the context of replicated append-only
logs. We wish to use append-only logs as a replication mechanism
because of their simple synchronization protocol (two peers just have
to compare their replica's height in order to find out which replica
contains more recent data). But because the logs are immutable,
storing updates regarding higher-level objects will accumulate in an
unbounded way.

In this work we show how specific higher-level data structures, a
dynamic LIST and a dynamic SET, can be mapped to an unbounded
append-only log yet we keep the relevant data in an _optimally bounded
contiguous section_ of the log. In other words, our encoding of the
mutable LIST and SET (called RoloLIST and RoloSET) permits to always
prune the log, meaning that we can ignore all log entries older that
some cutoff point. The following picture explains our approach of how
we handle the seemingly contradicting "immutability" vs "continuously
evolving" properties:

![A log wrapping around a monowheel cycle.](img/monowheel.png)

The current state of a LIST is stored in the red section of the log.
This includes information about the modification of the LIST, which is
added at the front of the log. In order to bound the red section and
declare _all entries older than the cutoff point_ (shown in green) as
being obsolete, most of the time it will be necessary to copy old data
to the front. The trick is to store enough "ordering information" with
the update details such that old LIST elements can be sitting at the
front of the log, instead of the natural creation order.

## History

This work is an extension of a technique described in the MSc thesis
of Sebastian Philipp at the University of Basel, 2022 with the
title _"Memory-Bounded Replication of Mutable Data Structures over
Immutable Append-Only Logs"_.

Philipp's encoding for a LIST data structure is based on storing, per
log entry, one to three basic operations: "create", "link" and
"head". These operations apply directlyto an in-memory representation
of the LIST. In this way, insertion as well as deletion (in the
in-memory representation) can be modeled as is shown in the example of
Figure 3.4, extracted from his report:

![Copy of Fig 3.4 in Philipp's MSc thesis, 2022, page 20](img/philipp-fig3.4.png)

### Aggressive Rollover and Continuous Pruning

We extend Philipp's technique by adding an aggressive pruning strategy
using "rollovers". Unless the modification of the LIST is about adding
or replacing a element (in which case we have to grow the "red
section"), all other actions _must_ lead to pruning at least one log
entry. In case that the to-be-pruned entry contains still relevant
data, we copy its content as well as "link rewiring instructions" to
the front of the log. This must be done in a careful way as it impacts
the main action on the LIST: For example, deleting an element requires
updating pointers in the adjacent elements, but now with the catch
that one of these elements could have been moved from the back to the
front of the log. This means that we have to _update the updating
information_ before writing the rewiring details to the log.

## Log Entry Encoding

For the internal implementation of a RoloLIST we chose a
double-linked list (written in small caps): This in-memory
double-linked list stores the high-level RoloLIST's elements. The
append-only log does not need to be aware of this double-linked list
and, in fact, only contains instructions for a single-linked list
implementation: It suffices to express manipulations of the elements'
```prev``` links because the other direction (```next```) can be
computed based on the in-memory data.

Differently from Philipp, we chose to keep track of a ```tail```
pointer instead of ```head```, assuming that it is more frequent that
elements are appended to a RoloLIST. The following examples show
log snapshots that result from translating a high-level action
(e.g. append a RoloLIST element) to the respective series of low-level
operations stored as one entry in the log.

The three available low-level operations to encode a high-level
action are shown here as tuples with their arguments:

```
(value "some data")    // corresponds to Philipp's ```create```
(link at to)           // in element 'at' replace the prev link by 'to' or nil
(tail to)              // define the new tail element value, can be nil
```

where ```at``` and ```to``` are pointers in form of sequence numbers
that identify what log entry is referenced. As with Philipp's encoding,
the default field values of the in-memory nodes of the double-linked
list are ```nil```.

# Examples

An empty RoloLIST can be encoded as
```
#1534 (tail nil)
```

```1534``` in this example is the sequence number at which an
entry is stored in the log; the rest of the line shows the content
of that entry.

Assuming the RoloLIST was empty and the log's height was 4474, when
the application issues an ```append("first element")```, we would
encode this as one log entry with two low-level operations:

```
#4475  (value "first element"), (tail 4475)
```

The two-element RoloLIST ```['first element','2nd element']```, for
example resulting from an additional high-level ```append("2nd
element")``` command, can be encoded as:

```
#4475  (value "first element"), tail(4475)
#4476  (value "2nd element)", link(4476, 4475), tail(4476)
```

The ```tail(4476)``` operation overrides the respective operation in
log entry ```4475```.

Striving for the same RoloLIST content as before, but doing a
one-element rollover that prunes away entry #4475, we can write an
entry #4477 such that the new log content defines the same high-level
RoloLIST, just stored one position further in the log:

```
#4476  (value "2nd element"), link(4476, 4475), tail(4476)
#4477  (value "first element"), link(4476, 4477)
```

As one can see, the _value_ for the first RoloLIST element is copied
over to the front of the log (note that implicitly, its ```prev``` pointer
is set to ```nil```).  Now that the "first element" has changed its
location to #4777, we need to change the ```prev``` link of the "2nd
element" (defined in #4476) and let it point to #4477, which is also
part of the operations in entry #4477.  The tail information, defined
in entry #4476, is still valid and does not need changing.


## Replay for Reconstruction

The contents of a single log entry is not necessarily valid if taken
out of context: Clearly, in the example above, #4476 contains wrong
pointer data.  But together with entry #4477, the high-level RoloLIST
is defined correctly. Our basic requirement is that the RoloLIST's or
RoloSET's content can be fully reconstructed by replaying exactly the
active log entries i.e., the "red section".

In our implementation we do this by sequentially executing the
operations in the log entries and updating the in-memory
representation of the RoloLIST or RoloSET.

In case of a full reconstruction from scratch, a first pass reads all
log entries after the prune cutoff point, creating nodes (for each
```value``` command), defining the ```prev``` link pointers where told
to do so, and setting the current tail value. When completed, a second
pass is necessary, now over the in-memory single-linked list, in order
to creating the ```next``` pointer values needed in our desired
in-memory double-linked list.  All nodes that were created in the
first phase but which are _not_ part of the final double-linked list
are not elements of the high-level RoloLIST and can be garbage
collected.


## A Python Library

```
class RoloSET:
  __len__()       return number of elements in the SET
  __iter__()      return iterator over all SET elements
  add(val)        add operation
  del(val)        delete operation
  ismember(val)   test for set membership
  clear()         delete all elements
  tidy()          do as many rollovers as necessary to remove all tombstones

class RoloLIST:
  __len__()       return number of elements in the LIST
  __iter__()      return iterator over all LIST elements
  append(val)     append at end of LIST
  insert(ndx,val) insert at given index
  set(ndx,val)    replace value at given index
  pop(ndx)        remove element at given index
  index(val)      return index of first occurence of given value
  clear()         delete all elements
  tidy()          do as many rollovers as necessary to remove all tombstones
```

... more text here ...


## Example of a Compact Encoding for tinySSB

TinySSB has a limitation of 48 Bytes per log entry (if not using
side-chains).  We implemented a "group membership" RoloSET where
members are identified by an opaque 32 Bytes value. The resulting
compact encoding that keeps within the 48B limit looks as follows:

```
+---+--+-+--------------------------------+----+----+--+
|MAG|SZ|F|               o0               | o1 | o2 |o3|
+---+--+-+--------------------------------+----+----+--+
  3  2  1                32                 4    4   2   = 48 Bytes

MAG    magic pattern (constant 'GMS' for "group membership set")
SZ     size (number of relevant log entries, including this one)
F      flags (4x2 bits: 00 unused, 01 value, 10 link, 11 tail)
o0..3  operations' parameters
```

The four fixed-length fields ```o0``` to ```o3``` contain the
parameters for the operations that are defined in the ```flags``` field.

In case of a ```value``` operation, the member identifier (32 Bytes
for a public ED25519 key) is put into the field ```o0```.

```Link``` operation parameters are 2 Bytes wide each, stored as
unsigned integers in network order, and are relative to the position
where the current entry is stored in the log. The number 1 thus refers
to the log entry just before the one that contains the reference.

The ```tail``` operation only needs one pointer value, also expressed
as a relative value and stored in 2 Bytes. The value 0xFFFF is
reserved for representing ```nil```.

By limiting the pointer parameters to a 2 Bytes range, this RoloSET
encoding for 48 Bytes-wide log entries still supports sets of up to
2^15 members, each being identified by a 32 Bytes value.


## Demo

...

---


