"""
Weak reference list.  Adapted from 
https://stackoverflow.com/questions/677978/weakref-list-in-python

Tested for append() and __iter__().

**WARNING:**
When the last element goes dead, __iter__() still givens len()=1 and returns the last element.
"""

import weakref

class WeakList(list):
	def __init__(self, seq=()):
		list.__init__(self)
		self._refs = []
		self._dirty=False
		for x in seq: self.append(x)

	def _mark_dirty(self, wref):
		self._dirty = True

	def flush(self):
		self._refs = [x for x in self._refs if x() is not None]
		self._dirty=False

	def __getitem__(self, idx):
		if self._dirty: self.flush()
		return self._refs[idx]()

	def __iter__(self):
		for ref in self._refs:
			obj = ref()
			if obj is not None: yield obj

	def __repr__(self):
		return "WeakList(%r)" % list(self)

	def __len__(self):
		if self._dirty: self.flush()
		return len(self._refs)

	def __setitem__(self, idx, obj):
		if isinstance(idx, slice):
			self._refs[idx] = [weakref.ref(obj, self._mark_dirty) for x in obj]
		else:
			self._refs[idx] = weakref.ref(obj, self._mark_dirty)
		
	def __delitem__(self, idx):
		del self._refs[idx]

	def append(self, obj):
		self._refs.append(weakref.ref(obj, self._mark_dirty))

	def count(self, obj):
		return list(self).count(obj)

	def extend(self, items):
		for x in items: self.append(x)
		
	def index(self, obj):
		return list(self).index(obj)
	
	def insert(self, idx, obj):
		self._refs.insert(idx, weakref.ref(obj, self._mark_dirty))
		
	def pop(self, idx):
		if self._dirty: self.flush()
		obj=self._refs[idx]()
		del self._refs[idx]
		return obj

	def remove(self, obj):
		if self._dirty: self.flush() # Ensure all valid.
		for i, x in enumerate(self):
			if x == obj:
				del self[i]
		
	def reverse(self):
		self._refs.reverse()

	def sort(self, cmp=None, key=None, reverse=False):
		if self._dirty: self.flush()
		if key is not None:
			key = lambda x,key=key: key(x())
		else:
			key = lambda x: x()
		self._refs.sort(cmp=cmp, key=key, reverse=reverse)

	def __add__(self, other):
		l = WeakList(self)
		l.extend(other)
		return l

	def __iadd__(self, other):
		self.extend(other)
		return self
		
	def __contains__(self, obj):
		return obj in list(self)

	def __mul__(self, n):
		return WeakList(list(self)*n)
		
	def __imul__(self, n):
		self._refs *= n
		return self
		
if __name__ == "__main__":
	class Obj(): 
		def __init__(self, s): self.s = s
	
	mylist = WeakList()
	s1 = Obj("s1")
	s2 = Obj("s2")
	s3 = Obj("s3")
	mylist.append(s1)
	mylist.append(s2)
	mylist.append(s3)
	print('--> 1,2,3')
	for s in mylist: print(s.s)
	s1 = None
	print('--> 2,3')
	for s in mylist: print(s.s)
	s2 = None
	print('--> 3')
	for s in mylist: print(s.s)
	del s3
	s3 = Obj("other")
	print('--> []')
	for s in mylist: print(s.s)
	print(len(mylist))
	s3 = Obj("s3'")
	mylist.append(s3)
	print('--> 3')
	for s in mylist: print(s.s)
	
