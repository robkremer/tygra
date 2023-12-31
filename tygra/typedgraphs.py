#! /usr/bin/env python3
"""
This module contains the 3 fundamental container objects for **tygra**:

*TygraContainer*:
   Represents a file and may contain several models and their associated views
   
*TGModel*:
   Represents a model and contains nodes and relations (but is no direction associated with a window or frame.
   
*TGView*:
   Represents a view of some model and contains visual representations of nodes and relations in its model.
   It DOES have an associated window or frame, and functions as a graph editor, viewing and possibly
   editing its model.
   
---------
"""
#################################################################################
# (c) Copyright 2023, Rob Kremer, MIT open source license.						#
#																				#
# Permission is hereby granted, free of charge, to any person obtaining a copy	#
# of this software and associated documentation files (the "Software"), to deal	#
# in the Software without restriction, including without limitation the rights	#
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell		#
# copies of the Software, and to permit persons to whom the Software is			#
# furnished to do so, subject to the following conditions:						#
#																				#
# The above copyright notice and this permission notice shall be included in all#
# copies or substantial portions of the Software.								#
# 																				#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR	#
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,		#
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE	#
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER		#
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,	#
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE	#
# SOFTWARE.																		#
#################################################################################

import sys
import os
import tkinter as tk
from tkinter import ttk
from tkinter import filedialog
from collections import namedtuple
from math import sqrt
import gc
import xml.etree.ElementTree as et
from ast import literal_eval
from typing import Any, Optional, Union, Tuple, Callable, Iterable, Dict, List
import webbrowser
import pathlib
from urllib.parse import urlparse
import urllib
from pip._vendor import requests
import tygra

sys.path.append(os.path.dirname(__file__))
from tygra.weaklist import WeakList
from tygra.util import PO, IDServer, AddrServer, Categories, bindRightMouse, \
	eventEqual, flattenPairs, s_SHIFT, normalizeRect, getCallerIdInfoStr
from tygra.mobjects import MObject, ModelObserver
from tygra.vobjects import VObject
from tygra.mnodes import MNode
from tygra.mrelations import MRelation, Isa
from tygra.vnodes import VNode
from tygra.vrelations import VRelation, VIsa
import tygra.app as app
from tygra.loggingPanedWindow import LoggingPanedWindow 
from tygra.prefs import Prefs, Pref
			
		
class _TempLogger: # A logger to use only until the constructor is far enough to use the real one.
	def write(self, s, **kwargs): 
		prefix = ""
		out = sys.__stdout__
		if "level" in kwargs:
			prefix = kwargs["level"] + ": "
			if prefix == "error: ":
				out = sys.__stderr__
		method = getCallerIdInfoStr()
		out.write(f'{prefix}: {s}\n  in {method}\n')
		
##########################################################################################
############################## class TygraContainer ################################
##########################################################################################

class TygraContainer(tk.Tk, IDServer, AddrServer):
	"""
	A top-level TK window displaying the model/view directory for a TypedGraphs file.
	Also acts as a top-level ID creation server and an id-to-address server for a all
	models/views in the file.
	"""
	
	_instances:WeakList = WeakList() # type: WeakList[Self]

	### Constructor and helpers ##########################################################
	
	def __init__(self, filename:Optional[str]=None, helppath:Optional[str]=None,
				geometry:Optional[str]=None):
		"""
		Returns a tk.TK window for the application. The contains a frame listing the models
		of views contained in a single file.
		
		:param filename: May have the following values:
		
			* the string "<new>": a new (empty) model and a single view of it are created;
			* a filename: attempts to open the file and interpret it as models and views;
			* *None*: A file open dialog box is presented and the result (if a file is 
					selected) proceeds as "filename", or (if the dialog box is cancelled)
					proceed as "<new>".
		:param helpPath: Either a file path or a URL to the root directory of the html help
			information for the program.
		:param goemetry: The initial geometry string for the window.
		"""
		self.logger = _TempLogger()
		super().__init__()
		TygraContainer._instances.append(self)
		self.option_add('*tearOff', tk.FALSE)
		self.menu = self.makeMenu()
		self.config(menu=self.menu)
		self.createcommand('tk::mac::ShowPreferences', self.showPreferencesDialog)
		self.createcommand('tk::mac::ShowHelp', self.showHelp)
		self.createcommand('::tk::mac::Quit', self.onQuit)
		self.protocol("WM_DELETE_WINDOW", self.onClosing)
		IDServer.__init__(self, None)
		AddrServer.__init__(self)
		self.nextID(0) # reserve id 0 for self
		self.views:List[TGView] = []
		self.models:List[TGModel] = []
		self.idRegister(app.CONTAINER_ID, self)
		self.directory = None
		self.topFrame = None
			
		# Do the file dialog thing
		self.filename = None
		if filename == '<new>': # special tag to force creation of a brand new model
			self.filename = None
			tree = None
		else:
			self.filename, tree = self.openFile(filename)

		# We have a filename, so build the actual interface
		self.logger = LoggingPanedWindow(self, None, fixedAppFrame=True)
		self.logger.setAppFrame(self.makeRecordsFrame(self.logger, tree=tree))		

#		if self.filename is not None: # we have filename, read it.
#			self.logger.setAppFrame(self.makeRecordsFrame(self.logger, tree=tree))
			
		# -or- Create a brand new model (either we were requested "<new>" or the user declined to open a file)
#		else: # create a brand new model and view
#			self.logger.setAppFrame(self.makeRecordsFrame(self.logger))
					
		self.title(f'{app.APP_LONG_NAME}{(": "+os.path.basename(self.filename)) if self.filename is not None else ""}')
		self.logger.write(f"{app.APP_LONG_NAME} file window initialized.")
		if geometry is not None:
			self.logger.winfo_toplevel().geometry(geometry)
			
		# set up prefs
		self.prefs = Prefs()
		self.helpURL = ""
		self.prefs.bind("helpURL", self, "text", "Help location", 
				help="A URI to the root directory of the program html help files. May be specified as an ordinary file path (which will be changed to a 'file:' URI).",
				validatorFunc=self.validateHelpURL, pythonType=str)
		self.prefs.bind("maxLevelStr", self.logger, "choices:normal:warning:informational:debug",
				"Message filter", help="The maximum severity level to display in the message pane.")
		self.prefs.bind("maxLines", self.logger, "int",
				"Max lines in log", help="The maximum number of lines to save in the message pane.")
		self.prefs.bind("DEBUG_MENUS", app, "bool",
				"Debug menus", help="Add debug options to menus.")
		try:
			self.prefs.read()
		except Exception as ex:
			self.logger.write(f'TygraContainer.__init__(): Exception while reading prefs.', exception=ex)
		
		# if helppath is given as a param, use that one by setting it in prefs (which also sets self.helpURL)
		try:
			if helppath is not None:
				self.prefs["helpURL"] = helppath
			assert self.helpURL is not None and len(self.helpURL)>0
		except:
			try:
				if self.helpURL is None or len(self.helpURL.strip())==0 or self.validateHelpURL(self.helpURL) is None:
					self.prefs["helpURL"] = "" # force an aggressive search
			except Exception as ex:
				self.owner.logger.write(f'Exception setting self.helpURL.', level="error")
		
	def destroy(self) -> None:
		TygraContainer._instances.remove(self)
		self.logger.delete()
		super().destroy()

	### Find the help files ##############################################################
	@staticmethod
	def validateHelpURL(value:str):
		# establish a default if necessary
		if value is None or len(value.strip())==0:
			# search for the html files
			dot, _ = os.path.split(__file__)
			places = [	os.path.join(dot,'html'),
						os.path.realpath(os.path.join(dot,'../html')),
						os.path.realpath(os.path.join(dot,'../sphinx/build/html'))]
			for p in places:
				if os.path.exists(os.path.join(p, 'typedgraphs.html')):
					value = p
					break
		# if the string is a file, turn it into a URI
		if urlparse(value).scheme == "": # helpPath isn't a URI
			helpURL = pathlib.Path(value).as_uri()
		else:
			helpURL = value
		if not helpURL.endswith('/'):
			helpURL += '/'
				
		# determine if the URI exists
		if str(helpURL).startswith("file:///"):
			if not os.path.exists(helpURL[7:].replace("%20"," ")):
				try:
					self.owner.logger.write(f'Can\'t find file {helpURL[7:].replace("%20"," ")}.', level="error")
				except:
					sys.__stderr__.write(f'Can\'t find file {helpURL[7:].replace("%20"," ")}.\n')
				helpURL = None
		else:
			ok = True
			statusCode = "request failed"
			try:
				r = requests.head(helpURL)
				statusCode = r.status_code
				if r.status_code != 200:
					ok = False
			except:
				ok = False
			if not ok:
				try:
					self.owner.logger.write(f'Can\'t find URL {helpURL}: Status code: {statusCode}.', level="error")
				except:
					sys.__stderr__.write(f'Can\'t find URL or invalid URL {helpURL}: Status code: {statusCode}.\n')
				helpURL = None
		return helpURL

	### Directory Frame and helpers ######################################################

	class ViewRecord:
		"""A veru simple record class for view information."""
		def __init__(self, master, initName:str, viewData):
			assert 	viewData is None or \
					isinstance(viewData, et.Element) or \
					isinstance(viewData, TGView)
			assert isinstance(initName, str)
			self.viewName = tk.StringVar(master, value=initName)
			self.viewData = viewData
	class ModelRecord:
		"""A very simple record class for Model information."""
		def __init__(self, master, initName:str, modelData, viewRecords:dict=dict()):
			assert 	modelData is None or isinstance(modelData, TGModel)
			assert isinstance(initName, str)
			self.modelName = tk.StringVar(master, value=initName)
			self.modelData = modelData
			self.viewRecords = viewRecords

	def makeRecordsFrame(self, parent=None, tree:Optional[et.Element]=None) -> tk.Frame:
		"""
		Make a frame showing the list of models and the sublists of thier views.
		
		There are 3 cases under which this method is called:
			1. We are making an original frame (*parent* is not None and *self.directory*
				is None)
			2. We are reading in a file (*tree* is not None and self.directory* is None)
			3. We have changed the dictionary and need to refresh the frame (*parent* and 
				*tree* are both None and *self.directory* is not None)
		"""
		# if this is the first call, create the frame, otherwise empty the frame to start afresh.
		if self.topFrame is None:
			assert parent is not None
			self.topFrame = tk.Frame(parent, width=300, height=50)
		else:
			for widget in self.topFrame.winfo_children():
				widget.destroy()
		
		if tree is None:
			if self.directory is None: # case 1 (new file)
				self.doNewModel(refreshRecordsFrame=False) # don't want to refresh
			else: # case 3 (refreshing after a directory change)
				pass
		else: # case 2 (reading in from a file)
			root = tree.getroot()
			if root.tag != "typedgraphs":
				raise ValueError(f'TygraContainer(): {self.filename} is not a typedgraphs file.')
			self.readDirectory(root)
			self.readModelsAndViews(root)
			geometry = root.get('geometry')
			if geometry is not None:
				self.winfo_toplevel().geometry(geometry)
			
		# set up the grid in the frame
		self.topFrame.columnconfigure(0, weight=0)
		self.topFrame.columnconfigure(1, weight=1)
		self.topFrame.columnconfigure(2, weight=0)
		
		# set up the actual rows of Entries and Buttons
		row = 0
#		self.openButtons = []
		for modelID, modelRecord in self.directory.items():
			e = tk.Entry(self.topFrame, textvariable=modelRecord.modelName)
			e.grid(row=row, columnspan=2, column=0, ipadx=1, ipady=1, padx=1, pady=1, sticky="NEWS")
			b = tk.Button(self.topFrame, text="model...", \
					command=lambda mr=modelRecord, r=row, id=modelID: self.doModelButton(mr, r, id)) #self.newViewButton(mr))
			b.grid(row=row, column=2, ipadx=1, ipady=1, padx=1, pady=1, sticky="NEWS")
			self.topFrame.rowconfigure(row, weight=1)

#			self.openButtons.append(b)
			row += 1
			for viewID, viewRecord in modelRecord.viewRecords.items():
				l = tk.Label(self.topFrame, text=' ')
				l.grid(row=row, column=0, ipadx=1, ipady=1, padx=1, pady=1, sticky="NWS")
				e = tk.Entry(self.topFrame, textvariable=viewRecord.viewName)
				e.grid(row=row, column=1, ipadx=1, ipady=1, padx=1, pady=1, sticky="NEWS")
				b = tk.Button(self.topFrame, text="view...", \
						command=lambda vr=viewRecord, r=row, id=viewID: self.doViewButton(vr, r, id))
				b.grid(row=row, column=2, ipadx=1, ipady=1, padx=1, pady=1, sticky="NEWS")
				self.topFrame.rowconfigure(row, weight=1)
#				self.openButtons.append(b)
				row += 1
				
		return self.topFrame

# TODO: set up reenabling the buttons when a view is closed

	def checkFileSignature(self, tree:et.Element) -> bool:
		"""Determine if *tree* is really a tygra xml file."""
		root = tree.getroot()
		return root.tag == "typedgraphs"
	
	def readDirectory(self, root:et.Element):
		"""
		Read the directory in *root* if there is one, placing the the resultant list of model and view
		records in *self.directory.  If there is not directory, *self.directory* will be an
		empty *dict*.
		"""
		self.directory:Dict[str,TygraContainer.ModelRecord] = dict()
		directoryElem = root.find('directory')
		if directoryElem is not None:
			for model in directoryElem.iterfind("model"):
				id = model.get('id')
				modelName = model.get('name')
				self.directory[id] = TygraContainer.ModelRecord(self, modelName, None, dict())
				for view in model.iterfind('view'):
					self.directory[id].viewRecords[view.get('id')] = \
						TygraContainer.ViewRecord(self, view.get('name'), None)

	def readModelsAndViews(self, root:et.Element):
		"""
		Read in the model and view elements from *root*, filling out their in *self.directory*.
		In the case of models, they models, the actual *TGModel* is constructed, whereas
		views are placed in *self.directory* only as their *ElemementTree.Element* structure.
		"""
		maxID = 0
		models = root.findall('TGModel')
		views = root.findall('TGView')
		for model in models:
			id = model.get('id')
			if self.getLocalID(id) > maxID: maxID = self.getLocalID(id)
			obj = PO.makeObject(model, self, TGModel)
			if id in self.directory:
				self.directory[id].modelData = obj
			else:
				self.directory[id] = TygraContainer.ModelRecord(self, id, obj, dict())
		for view in views:
			modelID = view.get('model')
			model = self.directory[modelID]
			id =  view.get('id')
			if self.getLocalID(id) > maxID: maxID = self.getLocalID(id)
			if id in model.viewRecords:
				model.viewRecords[id].viewData = view
			else:
				model.viewRecords[id] = TygraContainer.ViewRecord(self, id, view)
		self.nextID(maxID)
		
	### Directory popup menus and helpers ################################################

	def doModelButton(self, modelRecord:ModelRecord, row:int, id:str):
		"""
		Handle a "model" button event by putting up a popup menu for "new view" and "delete model".
		"""
		x, y, width, height = self.topFrame.grid_bbox(row=row, column=2)
		m = tk.Menu(self.topFrame)
		m.add_command(label="new view", command=lambda mr=modelRecord: self.doNewView(mr))
		m.add_command(label="delete model", command=lambda mr=modelRecord, id=id: self.doDeleteModel(mr, id))
		if app.DEBUG_MENUS:
			m.add_separator()
			m.add_command(label="validate", command=modelRecord.modelData.validate)
		x += self.topFrame.winfo_rootx()
		y += self.topFrame.winfo_rooty()
		m.post(x+5, y+10)
		
	def doViewButton(self, viewRecord:ViewRecord, row:int, id:str):
		"""
		Handle a "view" button event by putting up a popup menu for "open  view" and "delete view".
		"""
		x, y, width, height = self.topFrame.grid_bbox(row=row, column=2)
		m = tk.Menu(self.topFrame)
		m.add_command(label="open view", command=lambda vr=viewRecord, r=row: self.doOpenView(vr, r))
		m.entryconfigure('open view', \
				state=tk.NORMAL if isinstance(viewRecord.viewData, et.Element) else tk.DISABLED)
		m.add_command(label="delete view", command=lambda vr=viewRecord, id=id: self.doDeleteView(vr, id))
		x += self.topFrame.winfo_rootx()
		y += self.topFrame.winfo_rooty()
		m.post(x+5, y+10)		

	def doOpenView(self, rec:ViewRecord, row:int):
		"""
		Handle the event of the user selecting "open view" from the "view" popup menu by calling 
		*self.openView()*.  Throws exceptions if unexpected data times are encountered.
		"""
		if isinstance(rec.viewData, et.Element):
			rec.viewData = self.openView(rec.viewData)
		elif isinstance(rec.viewData, TGView):
			raise TypeError("TygraContainer.doOpenView(): Don't know what to do with an already-open TGView.")
		else:
			raise TypeError(f"TygraContainer.doOpenView(): Unexpected type: {type(rec.viewData).__name__}.")

	def doNewView(self, modelRecord:ModelRecord):
		"""
		Creates a brand new view for the *model*, updating *self.directory*, opening the *TGView* window,
		and populating it with nodes from the model that directly inherit from *topNode*. 
		"""
		view = TGView(self, self, modelRecord.modelData, self)
		self.directory[modelRecord.modelData.idString].viewRecords[view.idString] = \
				TygraContainer.ViewRecord(tk.StringVar(value=view.idString), view)
		self.makeRecordsFrame()
		for mn in view.model._nodes:
			if view.model.topNode in mn.isparent() and not view.categories.isCategory(mn, view.hiddenCategories):
				vn = view.makeViewObjectForModelObject(mn)
				vn.expand()
		layouts.IsaHierarchyHorizontalCompressed(view)()
		
	# TODO: bug: for some reason the .idString names don't show up in the tk.Entry's boxes. They do when it's read in from XML...
	def doNewModel(self, refreshRecordsFrame=True):
		"""
		Creates a brand new model, updating *self.directory*, then calls *self.makeRecordsFrame()*
		to update the records in the *TypedGraphsContainter* window. 
		"""
		model = TGModel(self, self)
		view = TGView(None, self, model)
		viewRecord = {view.idString: TygraContainer.ViewRecord(self, view.idString, view)}
		if self.directory is None:
			self.directory = dict()
		self.directory[model.idString] = TygraContainer.ModelRecord(self, \
				model.idString,
				model, viewRecord)
		if refreshRecordsFrame:
			self.makeRecordsFrame()
		
	# TODO: when a view id deleted, there is nothing done about checking for and closing its view window.
	def doDeleteView(self, rec:ViewRecord, id:str):
		"""
		Deletes the "rec" from *self.directory* and calls *self.RecordsFrame() to update the 
		*TypedGraphsContainter* window.
		"""
		for k, mr in self.directory.items():
			if id in mr.viewRecords:
				mr.viewRecords.pop(id)
				self.makeRecordsFrame()
				return
		self.logger.write(f'Can\'t find view id "{id}" to remove.')
		
	def doDeleteModel(self, modelRecord:ModelRecord, id:str):
		"""
		Deletes *modelRecord* from *self.directory* and calls *self.RecordsFrame() to update the 
		*TypedGraphsContainter* window.
		"""
		self.directory.pop(id)
		self.makeRecordsFrame()
		
	def onClosing(self):
		"""
		:param quitting: if True and this is the last file window to be closed, 
			calls *self.prefs.save()* to save the preferences and the open 
			window (a geometry info); if False calls *self.saveFile()*\ .
		The "close" button on the file window has been chosen, so (user optionally)
		save the file, and if this the last window standing, then save the 
		preferences too. 
		"""
		if len(TygraContainer._instances) < 2: 
			self.prefs.save()
		else:
			self.saveFile()
		self.destroy()
		
	def onQuit(self):
		"""
		The "quit application" menu item has been chosen. Saves the prefs (which
		itself uses the "save file" dialog to save all file data) the calls the
		*onClosing()* method on each of the files with the *quitting* flag to
		prevent the *onClosing() methods from using the "save file" dialogs again.
		"""
		self.prefs.save()
		files = []
		for c in TygraContainer._instances:
			c.destroy()
		exit(0) # would exit anyway, but here just in cose
		
	def setModelName(self, model, name:str):
		"""Sets the entry for *model* to *name* in *self.directory*."""
		self.directory[model.idString].modelName.set(name)
				
	def setViewName(self, view, name:str):
		"""Sets the entry for *view* to *name* in *self.directory*."""
		self.directory[view.model.idString].viewRecords[view.idString].viewName.set(name)

	def getViewsFromDirectory(self) -> dict:#[str, Self.ViewRecord]:
		ret = dict()
		for dirModelID, dirModelRec in self.directory.items():
			for dirViewID, dirViewRec in dirModelRec.viewRecords.items():
				ret[dirViewID] = dirViewRec
		return ret

	def lookupViewInDirectory(self, id:str) -> ViewRecord:
		for dirModelID, dirModelRec in self.directory.items():
			if id in dirModelRec.viewRecords:
				return dirModelRec.viewRecords[id]
		return None
	
	def lookupNameInDirectory(self, id:str) -> str:
		if self.directory is None: return id
		if id in self.directory:
			return self.directory[id].modelName.get()
		for dirModelID, dirModelRec in self.directory.items():
			if id in dirModelRec.viewRecords:
				return dirModelRec.viewRecords[id].viewName.get()
		return id
		
	### Persistence ######################################################################

	def openFile(self, filename:Optional[str]=None) -> Tuple[Optional[str], Optional[et.Element]]:
		"""
		:param filename: A filename to read. If this is *None* using the open-file dialog
					to get an actual filename.
		:return: A tuple of (filename, et.Element) or (None, None) if the user cancels.
				
		Reads a file from *filename* (or gets filename from the open-fine dialog) using 
		an xml parser. Queries the user to repeat if the filename is bad or the file is 
		signature is not correct.
		"""
		if filename is None or len(filename) == 0:
			if self.filename is not None:
				directory, fname = os.path.split(self.filename)
			else:
				directory ='.'
				fname=None
			filename = tk.filedialog.askopenfilename(parent=self,
						title='TG Open File', 
						initialdir=directory,
						initialfile=fname,
						filetypes=[('TG', f'*.{app.APP_FILE_EXTENSION}'), ('XML', '*.xml')])
		if filename == None or len(filename) == 0:
			return None, None
		if os.path.isfile(filename):
			self.filename = filename
			tree = et.parse(filename)
			if not self.checkFileSignature(tree):
				resp = tk.messagebox.askyesno(title='TG', message=f'file "{filename}" is not a TypedGraphs file. Do you want to try another file?')
				if resp == tk.YES:
					return self.openFile()
				else:
					return None, None
			return filename, tree
		else:
			resp = tk.messagebox.askyesno(title='TG', message=f'file "{filename}" does not exit. Do you want to try another file?')
			if resp == tk.YES:
				return self.openFile()
			else:
				return None, None
				
	def openView(self, elem:et.Element):
		"""
		Given a TGView element, return a *TGView* object.
		"""
		if elem.tag != "TGView":
			raise ValueError(f'TygraContainer.openView(): argument is not a TGView element.')
		ret = PO.makeObject(elem, self, TGView)
		viewRec = self.lookupViewInDirectory(ret.idString)
		viewRec.viewData = ret
		return ret
		
	def notifyViewDeleted(self, view):
		"""
		The view is notifying us that it's been deleted. Remove the view from *self.views*, and change
		*self.directory* to refer to the view by it's element (using *view.serializeXML()*), rather than
		its *TGView* representation.
		"""
		if view in self.views:
			self.views.remove(view)
		else:
			self.logger.write(f'Trying to delete an unregisterd view {view.idString}.', level='warning')
		modelID = view.model.idString
		viewRecord = self.directory[modelID].viewRecords[view.idString]
		viewRecord.viewData = view.serializeXML()
		
	def openNewFileInstance(self, filename:Optional[str]=None):
		"""
		Open a new instance of a *TypedgraphsContainer* and call it *mainloop()*.
		"""
		root = TygraContainer(filename)
#		root.mainloop()

	def saveFile(self):
		"""
		Save this instance into a file using the *tk.filedialog.asksaveasfilename()* dialog.
		"""
		if self.filename:
			dir, file = os.path.split(self.filename)
		else:
			dir = '.'
			file = None
		filename = tk.filedialog.asksaveasfilename(parent=self,
					title='TG Save to File', 
					initialdir=dir, 
					filetypes=[('TG', f'*.{app.APP_FILE_EXTENSION}'), ('XML', '*.xml')],
					defaultextension=f'*.{app.APP_FILE_EXTENSION}',
					initialfile=file)
		if filename is None or filename == "":
			return
		topElem = et.Element("typedgraphs")
		topElem.set('id', app.CONTAINER_ID)
		topElem.set('version', '0.0')
		topElem.set('geometry', self.winfo_toplevel().geometry())
		dir = et.Element('directory')
		for mid, mr in self.directory.items():
			mElem = et.Element('model')
			mElem.set('id', mid)
			mElem.set('name', mr.modelName.get())
			for vid, vr in mr.viewRecords.items():
				vElem = et.Element('view')
				vElem.set('id', vid)
				vElem.set('name', vr.viewName.get())
				mElem.append(vElem)
			dir.append(mElem)
		topElem.append(dir)
		for m in self.models:
			x = m.serializeXML()
			topElem.append(x)
		for v in self.views:
			x = v.serializeXML()
			topElem.append(x)
		for mid, mr in self.directory.items():
			for vid, vr in mr.viewRecords.items():
				saved = False
				for v in self.views:
					if v.idString == vid:
						saved = True
						break
				if not saved:
					if isinstance(vr.viewData, TGView):
						x = vr.viewData.serializeXML()
					elif isinstance(vr.viewData, et.Element):
						x = vr.viewData
					else:
						assert False, f"TygraContainer.saveFile(): Expecting either a TGView or a et.Element, got {type(v).__name__}."
					topElem.append(x)
		tree = et.ElementTree(element=topElem)
		et.indent(tree, space='  ', level=0)
		tree.write(filename, xml_declaration=True, encoding="utf-8")
		self.filename = filename
		self.logger.write(f'Saved to {self.filename}', level='info')
		
	### Menu Bar menus and helpers #######################################################

	def makeMenu(self) -> tk.Menu:
		"Construct and return the menubar menu for the app. This method does NOT add the menu to the app menu bar."
		menubar = tk.Menu(self)
		
		appmenu = tk.Menu(menubar, name="apple")
		appmenu.add_command(label="About...", command=self.showAbout)
		appmenu.add_separator()
		menubar.add_cascade(menu=appmenu)
			
		# file menu
		filemenu = tk.Menu(menubar)
		newmenu = tk.Menu(filemenu)
		newmenu.add_command(label="New File", command=lambda: self.openNewFileInstance('<new>'))
		newmenu.add_command(label="New Model", command=lambda: self.doNewModel()) # want to refresh
		filemenu.add_cascade(label="New", menu=newmenu)
		filemenu.add_command(label="Open...", command=self.openNewFileInstance)
		filemenu.add_command(label="Save...", command=self.saveFile)
		menubar.add_cascade(label="File", menu=filemenu)
		
		# MacOS automatically fills this in for us...
		windowmenu = tk.Menu(menubar, name='window')
		menubar.add_cascade(menu=windowmenu, label='Window')

		helpmenu = tk.Menu(menubar, name="help") # on Mac, the "Python help" menu item automatically shows up.
		menubar.add_cascade(label="Help", menu=helpmenu)

		return menubar
		
	# TODO: Implement application help
	def showHelp(self, relPagePath:str="index.html"):
		"""
		:param relPagePath: the path, relative to the help root directory, of the help page requested. [default: "index.html"]
		Show help info for the application.
		"""
		url = urllib.parse.urljoin(self.helpURL, relPagePath)
		try:
			if str(url).startswith("file:///"):
				if os.path.exists(url[7:].replace("%20"," ")):
					webbrowser.open(url, new=0, autoraise=True)
				else:
					self.logger.write(f'Can\'t find file {url[7:]}.', level="error")
			else:
				r = requests.head(url)
				if r.status_code == 200:
					webbrowser.open(url, new=0, autoraise=True)
				else:
					self.logger.write(f'Can\'t find URL {url}: Status code {r.status_code}.', level="error")
		except Exception as ex:
			self.logger.write(f"cannot open {url}.", level="error", exception=ex)
		
	def showAbout(self):
		"""
		Show the about information.
		"""
		tk.messagebox.showinfo(
			parent=self,
			icon="info",
			title=f'About {app.APP_LONG_NAME}',
			message=f'''{app.APP_LONG_NAME}, version {app.VERSION}
						  by Rob Kremer''',
			)

	def showPreferencesDialog(self):
		"""
		Bring up the preferences dialog.
		"""
		self.prefs.edit(self, "Tygra Preferences")
			
##########################################################################################
################################## class TGModel #########################################
##########################################################################################

class TGModel(PO, IDServer):
	"""
	A non-user interfaced container class for a graph *model*\ . It contains objects of
	types :class:`mnodes.MNode`, :class:`mrelations.MRelation`, and :class:`mrelations.Isa`. 
	Users extend and edit models though views (:class:`TGView`). A model builds the fundamental
	nodes and relations automatically during it's construction; these are NOT stored with
	the model data when it is serialized to a file. These are:
	
	* T: The "top" node, base type for all nodes.
	* REL: The base type for all relations.
	* TRANS: TRANS <: REL. The type for transitive relations.
	* REFL: REFL <: REL. The type for reflexive relations.
	* SYM: SYM <: REL. The type for symmetric relations.
	* ISA: ISA <: TRANS, REFL. The type for isa (subsumption) relations.
	"""

	@property
	def logger(self):
		try:
			return self.container.logger
		except:
			return self._tempLogger
			
	def __init__(self, container:TygraContainer, idServer:IDServer=None, 
				addrServer:AddrServer=None, _id:Optional[int]=None):
		self.container:TygraContainer = container
		container.models.append(self)
		self._tempLogger = _TempLogger()
		# call the IDServer constructor
		IDServer.__init__(self, parent=container, _id=_id)
		
		# call the PO (persistent object) constructor
		PO.__init__(self, idServer=idServer if idServer else container, _id=_id)
		
		
		self._nodes:List[MNode] = []
		self._relations:List[MRelation] = []
		self.observers = WeakList()
		
		self.topNode = None
		self.topRelation = None

		# (1,0)
		self.topNode = MNode(self, idServer=self)
		self.topNode.attrs["fillColor"] = "white"
		self.topNode.attrs["borderColor"] = "black"
		self.topNode.attrs["textColor"] = "black"
		from tygra.vnodes import Shape
		self.topNode.attrs.add("shape", "Rectangle", kind='choices', validator=Shape.shapeValidator)
		self.topNode.attrs["aspectRatio"] = 0.5
		self.topNode.attrs["minSize"] = 80
		self.topNode.attrs.add("label", app.TOP_NODE, default="")
		self.topNode.attrs.add("type", True, kind='bool', default=False, editable=False)
		self.topNode.attrs.add("notes", "All nodes inherit from this one.", kind='mtext', default="")
#		self.logger.write(f'topNode: {self.topNode.idString}', level='debug')

		# (1,1)
		self.topRelation = MRelation(self, frm=self.topNode, to=self.topNode, typ=None, idServer=self)
		self.topRelation.attrs["fillColor"] = "white"
		self.topRelation.attrs["borderColor"] = "black"
		self.topRelation.attrs["textColor"] = "black"
		self.topRelation.attrs["shape"] = "Oval"
		self.topRelation.attrs["lineColor"] = "black"
		self.topRelation.attrs["aspectRatio"] = 1.0
		self.topRelation.attrs["minSize"] = 30
		self.topRelation.attrs.add("label", app.TOP_RELATION)
		self.topRelation.attrs.add("type", True, kind='bool', default=False, editable=False)
		self.topRelation.attrs.add("notes", "All relations inherit from this one.", kind='mtext', default="")
#		self.logger.write(f'topRelation: {self.topRelation.idString}', level='debug')

		# (1,2), isa:(1,3)
		self.reflexiveRelation = MRelation(self, frm=self.topNode, to=self.topNode, typ=self.topRelation, idServer=self)
		self.reflexiveRelation.attrs.add("relationProperties", set(["ReflexiveProperty"]), kind='set', system=True)
		self.reflexiveRelation.attrs["label"] = "REFLEXIVE"
		self.reflexiveRelation.attrs.add("type", True, kind='bool', default=False, editable=False)				
#		self.logger.write(f'reflexiveRelation: {self.reflexiveRelation.idString}', level='debug')

		# (1,4), isa:(1,5)
		self.symmetricRelation = MRelation(self, frm=self.topNode, to=self.topNode, typ=self.topRelation, idServer=self)
		self.symmetricRelation.attrs.add("relationProperties", set(["SymmetricProperty"]), kind='set', system=True)
		self.symmetricRelation.attrs["label"] = "SYMMETRIC"
		self.symmetricRelation.attrs.add("type", True, kind='bool', default=False, editable=False)
#		self.logger.write(f'symmetricRelation: {self.symmetricRelation.idString}', level='debug')

		# (1,6), isa:(1,7)
		self.transitiveRelation = MRelation(self, frm=self.topNode, to=self.topNode, typ=self.topRelation, idServer=self)
		self.transitiveRelation.attrs.add("relationProperties", set(["TransitiveProperty"]), kind='set', system=True)
		self.transitiveRelation.attrs["label"] = "TRANSITIVE"
		self.transitiveRelation.attrs.add("type", True, kind='bool', default=False, editable=False)
#		self.logger.write(f'transitiveRelation: {self.transitiveRelation.idString}', level='debug')
		
		# (1,8), isa:(1,9)
		self.isa = Isa(self, frm=self.topNode, to=self.topNode, idServer=self)
		self.isa.attrs["fillColor"] = ""
		self.isa.attrs["borderColor"] = ""
		self.isa.attrs["textColor"] = "blue"
		self.isa.attrs["lineColor"] = "blue"
		self.isa.attrs.add("lineWidth", 2, kind='int')
		self.isa.attrs["shape"] = "Oval"
		self.isa.attrs["label"] = app.ISA
		self.isa.attrs.add("type", True, kind='bool', default=False, editable=False)
#		self.logger.write(f'isa: {self.isa.idString}', level='debug')

		isa = Isa(self, frm=self.isa, to=self.transitiveRelation, idServer=self)

		self.nextID(app.RESERVED_ID)
		
	def validate(self):
		errors = 0
		for n in self._nodes:
			errors += n.validate()
		for n in self._relations:
			errors += n.validate()
		if errors == 0:
			self.logger.write(f'No errors.', level="normal")
		else:
			self.logger.write(f'{errors} validation errors.', level="error")
		
	def register(self, obj: Union[MRelation, MNode]):
		if   isinstance(obj, MRelation):
			self._relations.append(obj)
			self.notifyObservers(obj, "add rel")
		elif isinstance(obj, MNode):
			self._nodes.append(obj)
			self.notifyObservers(obj, "add node")
		else:
			raise TypeError(f'TGModel.register(): unexpected type {type(obj).__name__}')
		
	def unregister(self, obj: Union[MRelation, MNode]):
		if   isinstance(obj, MRelation):
			if obj in self._relations:
				self._relations.remove(obj)
				self.notifyObservers(obj, "del rel")
			else:
				self.logger.write(f'attempt to remove unknown MRelation {obj.stringID}, "{obj.attrs["label"]}".', level='warning')
		elif isinstance(obj, MNode):
			if obj in self._nodes:
				self._nodes.remove(obj)
				self.notifyObservers(obj, "del node")
			else:
				self.logger.write(f'attempt to remove unknown MNode {obj.stringID}, "{obj.attrs["label"]}".', level='warning')
		else:
			raise TypeError(f'unexpected type {type(obj).__name__}')

	### Persistence ######################################################################

	def serializeXML(self) -> et.Element:
		"""
		Returns the representation of this object as an Element object.
		Implementors should call *super().serializeXML()* **first** as this top-level method
		will construct the Element itself.
		"""
		elem = PO.serializeXML(self) # selective "super()"
		
		# save nodes
		nodes = et.Element("nodes")
		elem.append(nodes)
		for n in self._nodes:
			if n.id >= app.RESERVED_ID:
				try:
					x = n.serializeXML()
					nodes.append(x)
				except Exception as ex:
					self.logger.write(f'Unexpected exception calling serializeXML() on node "{n}". Node not saved.', level="error", exception=ex)
			
		# save relations
		rels = et.Element("relations")
		elem.append(rels)
		for r in self._relations:
			if r.id >= app.RESERVED_ID:
				try:
					x = r.serializeXML()
					rels.append(x)
				except Exception as ex:
					self.logger.write(f'Unexpected exception calling serializeXML() on relation "{r}". Relation not saved.', level="error", exception=ex)
			
		return elem

	@classmethod
	def getArgs(cls, elem: et.Element, addrServer:AddrServer) -> Tuple[List[Any], Dict[str, Any]]:
		args = []
		kwargs = dict()
		container = addrServer.idLookup(app.CONTAINER_ID)
		args.append(container)

		idStr = elem.get('id')
		id = IDServer.getLocalID(idStr) if idStr else None
		kwargs["_id"] = id
		kwargs["idServer"] = container
		kwargs["addrServer"] = container
		
		return args, kwargs
	
	def unserializeXML(self, elem: et.Element, addrServer:AddrServer):
		"""
		This object is partially constructed, but we need to restore this class's bits.
		Implementors should call *super().xmsRestore()* at some point.
		"""
		self.readingPersistentStore = True
		try:
			super().unserializeXML(elem, addrServer)
			
			# register all the system MObjects with the AddrServer
			for n in self._nodes+self._relations:
				addrServer.idRegister(n.idString, n)
				assert n.system
				
			# load in the nodes
			nodes = elem.find("nodes")
			for subelem in nodes.iterfind("*"):
				node = self.makeObject(subelem, addrServer, MNode) # The mnodes will enter themselves into self._nodes
				if node.attrs.get("label", includeInherited=False) == app.TOP_NODE:
					self.topNode = node
					
			# load the relations
			rels = elem.find("relations")
			for subelem in rels.iterfind("*"):
				try:
					rel = self.makeObject(subelem, addrServer, MRelation) # The mrelations will enter themselves into self._nodes
					if rel.attrs.get("label", includeInherited=False) == app.TOP_RELATION:
						self.topRelation = rel
					if rel.attrs.get("label", includeInherited=False) == app.ISA:
						self.isa = rel
				except Exception as ex:
					self.logger.write(f'Exception instantiating {subelem.get("id")}.', level='warning', exception=ex)
			# in case there were any address-lookup faults, give the relations a chance to fix it.
			
			# let the relations finish up
			# isa's first, as they other relations usually have constraints based on isa's
			for r in self._relations:
				if r.id < app.RESERVED_ID: continue
				if isinstance(r, Isa):
					try:
						r._post__init__(addrServer)
					except Exception as ex:
						self.logger.write(f'exception in _post__init__() of {r}. (Object will be deleted.)', level='warning', exception=ex)
						r.delete()
			for r in self._relations:
				if r.id < app.RESERVED_ID: continue
				if not isinstance(r, Isa):
					try:
						r._post__init__(addrServer)
					except Exception as ex:
						self.logger.write(f'exception in _post__init__() of {r}. (Object will be deleted.)', level='warning', exception=ex)
						r.delete()


			# in the case of an "empty" model, we need to fix nextID()
			if self._nextID <= app.RESERVED_ID:
				self.nextID(app.RESERVED_ID)
		finally:
			self.readingPersistentStore = False

	### Observer #########################################################################

	def addObserver(self, observer:ModelObserver):
		if not isinstance(observer, ModelObserver):
			raise TypeError(f'TGModel.addObserver(): argument of type {type(observer).__name__} is not a ModelObserver.')
		self.observers.append(observer)
		
	def removeObserver(self, observer:ModelObserver):
		self.observers.remove(observer)
		
	def notifyObservers(self, obj:MObject, op:Any=None):
		for o in self.observers:
			o.notifyModelChanged(obj, op)

	### Utility ##########################################################################
	
	def makeNode(self, typ=None):
		"""
		:param typ:
		:type typ: Union[Self,List[Self],None]
		"""
		return MNode(self, typ, idServer=self)

	def makeRelation(self, fromNode:MObject, toNode:MObject, typ:Union[MRelation, List[MRelation]]):
		"""
		Return a new relation, unless there already is such a relation, then return that.
		
		:param typ:
		:type typ: Union[Self,List[Self],None]
		"""
		assert isinstance(fromNode, MObject)
		assert isinstance(toNode, MObject)
		if not isinstance(typ, list):
			typ = [typ]
		for t in typ:
			assert isinstance(t, MRelation)
			for r in fromNode.relations:
				if toNode is r.toNode and not r.isIsa and r.isa(t):
					return r # we already have such a relation
		return MRelation(self, fromNode, toNode, typ, idServer=self)


##########################################################################################
################################### class TGView #########################################
##########################################################################################

	
		
class TGView(tk.Canvas, PO, IDServer, ModelObserver):
	"""
	The actual graph editor Canvas. Quite a large class, handling the user interaction. It's
	a container for visual objects, :class:`vnodes.VNode`\ , :class:`vrelations.VRelation` 
	and :class:`vrelations.VIsa`\ . All of these reference their model counterparts for
	actual semantic information (such a relations and type constraints), in addition to 
	shared visual attributes (such as fillColor, bounderColor, shape, and label).
	"""

	makeRelationData = namedtuple('makeRelationData', 'node type lineID')
	
	def _clearIdLookupTable(self, addrServer, _id):
		#debug
		total = 1000
		lastTotal = 1001
		while total>0:
			total = 0
			keys = []
			for k,v in addrServer.idLookupTable.items():
				id = IDServer.makeIDTuple(k)
				if id[0] == _id:
					keys.append(k)
					total += 1
					refs = gc.get_referrers(v)
					for r in refs:
						if isinstance(r, VObject) or isinstance(r, MObject):
							text = r.idString
						else:
							text = repr(r)
			if lastTotal == total:
				print(f'Failed to clear idLoopupTable. Forcably removing {keys}.')#, level='warning')
				for k in keys:
					addrServer.idLookupTable.pop(k)
# 				return
			lastTotal = total
			refs = None
			keys = None
			gc.collect()

	def __init__(self, tkparent, container:TygraContainer, model:TGModel, 
				idServer:IDServer=None, _id:Optional[int]=None, 
				hiddenCategories:Optional[List[str]]=None, windowGeometry:Optional[str]=None, 
				**kwargs):

		self._clearIdLookupTable(container, _id)	

		### call the IDServer's constructor
		id = _id
		IDServer.__init__(self, parent=container, _id=id)
		
		### call the PO (Persistent Object) constructor 	
		PO.__init__(self, idServer=idServer if idServer else container, _id=_id)

		### TGview stuff
		self.readingPersistentStore = False
		self.container:TygraContainer = container
		if model == None:
			model = TGModel(container)
		self.model:TGModel = model
		self.model.addObserver(self)
		self.container.views.append(self)
		self.nodes:List[VNode] = []
		self.relations:List[VRelation] = []
		self.isModelEditor = True
		self._suppressLocalLayout = False
		self.newNodeCoords = (0, 0)
		self._fontFace = "TkMenuFont"
		self._fontSize = 12
		self._scale = 1.0
		self.newNodeDisplaySelectionPolicy = None
		self.setNewNodeDisplaySelectionPolicy()
		self.layoutObjects:Dict[str,layouts.LayoutHieristic] = {
				"ISA hierarcy (vert)": layouts.IsaHierarchy(self),
				"ISA hierarcy (vert, tight)": layouts.IsaHierarchyCompressed(self),
				"ISA hierarcy (horz)": layouts.IsaHierarchyHorizontal(self),
				"ISA hierarcy (horz, tight)": layouts.IsaHierarchyHorizontalCompressed(self),
				"find free": layouts.FindFree(self),
				"find free (tight)": layouts.FindFree(self, spacing=[0,0,0,0], relSpacing=[-4,-4,-4,-4]),
				"nudge": layouts.Nudge(self),
				"nudge (tight)": layouts.Nudge(self, spacing=[0,0,0,0], relSpacing=[-4,-4,-4,-4]),
				}
		self.localLayoutName = "find free"
		self.setLocalLayout(self.layoutObjects[self.localLayoutName], name=self.localLayoutName)
		assert isinstance(self.localLayout, layouts.LayoutHieristic)
		self.selected = set() # Used by VNodes for noting selection groups
		self._scrolling = False
		self._selectionBoxInfo = None

		### windowing stuff
		self.scrollRegion = (0, 0, 4000, 3000)
		if tkparent==None:
			tkparent = container
		child_w = tk.Toplevel(tkparent)
		child_w.geometry("750x400" if windowGeometry is None else windowGeometry)
		file = (": "+os.path.basename(self.container.filename)) if self.container.filename is not None else ""
		child_w.title(f'{app.APP_LONG_NAME}{file}: view "{self.container.lookupNameInDirectory(self.idString)}" of model "{self.container.lookupNameInDirectory(model.idString)}"')

		self.logger = LoggingPanedWindow(child_w, logFiles=sys.stdout)
		self.frame = self.logger.appFrame
				
		if "scrollregion" not in kwargs:
			kwargs["scrollregion"] = self.scrollRegion
		self.h = ttk.Scrollbar(self.frame, orient=tk.HORIZONTAL)
		self.v = ttk.Scrollbar(self.frame, orient=tk.VERTICAL)
		kwargs["yscrollcommand"] = self.v.set
		kwargs["xscrollcommand"] = self.h.set

		# Call the tk.canvas constructor
		super().__init__(self.frame, **kwargs)

		self.h['command'] = self.xview
		self.v['command'] = self.yview

		self.grid(column=0, row=0, sticky=(tk.N, tk.W, tk.E, tk.S))
		self.h.grid(column=0, row=1, sticky=(tk.W, tk.E))
		self.v.grid(column=1, row=0, sticky=(tk.N, tk.S))
		self.frame.grid_columnconfigure(0, weight=1)
		self.frame.grid_rowconfigure(0, weight=1)
		
		self.logger.write("Welcome to TypedGraphs!")

		### More TGview stuff
		self.makeBindings();
		self._eventHandled = None
		self._makingRelationFrom = None
		self.categories = Categories[MObject]()
		self.categories.addCategory("system", lambda n: (n.system or n.toNode.system or n.fromNode.system) if isinstance(n, MRelation) else n.system)
		self.categories.addCategory("type", lambda n: (n.attrs['type'] or n.toNode.attrs['type'] or n.fromNode.attrs['type']) \
										if isinstance(n, MRelation) else n.attrs['type'])
		self.categories.addCategory("individual node", lambda n: isinstance(n, MNode) and not n.attrs['type'])
		self.categories.addCategory("individual relation", lambda n: isinstance(n, MRelation) and not n.attrs['type'])
		self.categories.addCategory("higher order", lambda n: isinstance(n, MRelation) \
					and (n.attrs['type'] \
						or (isinstance(n.fromNode, MRelation) and n.fromNode.attrs['type']) \
						or (isinstance(n.toNode, MRelation) and n.toNode.attrs['type'])))
		self.categories.addCategory("isaRelations", lambda n: isinstance(n, MRelation) and n.isIsa)
		self.hiddenCategories = set(["system", "higher order"]) if hiddenCategories is None else set(hiddenCategories)

	def writeToLog(self, msg):
		numlines = int(self.textArea.index('end - 1 line').split('.')[0])
		self.textArea['state'] = 'normal'
		if numlines==24:
			self.textArea.delete(1.0, 2.0)
		if self.textArea.index('end-1c')!='1.0':
			self.textArea.insert('end', '\n')
		self.textArea.insert('end', msg)
		self.textArea['state'] = 'disabled'
		
	def makeBindings(self):		
		# For making relations
		self.bind("<B1-ButtonRelease>", self.onB1_ButtonRelease)
		self.bind("<Motion>", self.onMotion)
		
		# for popup menu
		bindRightMouse(self, self.onRightMouse)  #lambda e: self.backgroundMenu(e).post(e.x_root, e.y_root))

		# scroll using mouse click-and-drag
		self.bind("<Button-1>", self.onButton_1)
		self.bind("<B1-Motion>", self.onB1_Motion)
		# scroll using two-finger drag
		self.bind('<MouseWheel>', self.onMouseWheel)
		self.bind('<Shift-MouseWheel>', self.onShift_MouseWheel)
	
	def setScrollRegion(self, size:Optional[Tuple[int,int]]=None):
		if size is None:
			maxx = 0
			maxy = 0
			for n in self.nodes+self.relations:
				bb = n.boundingBox()
				if bb[2] > maxx: maxx = bb[2]
				if bb[3] > maxy: maxy = bb[3]
			maxx += 500
			maxy += 500
			if maxx < 4000: maxx = 4000
			if maxy < 3000: maxy = 3000
			self.scrollRegion = [0, 0, int(maxx), int(maxy)]
		else:
			self.scrollRegion = [0, 0, size[0], size[1]]
		self.configure(scrollregion=self.scrollRegion)
		
	def incrementScrollRegion(self, by:Tuple[int,int]=(1000,750)):
		self.scrollRegion = [0, 0, self.scrollRegion[2]+by[0], self.scrollRegion[3]+by[1]]
		self.configure(scrollregion=self.scrollRegion)
		
	def destroy(self):
		try:
			self.container.notifyViewDeleted(self)
		except:
			pass
		for r in self.relations:
			try:
				r.delete()
			except:
				pass
		for n in self.nodes:
			try:
				n.delete()
			except:
				pass
		self.container = None
		self.relations = None
		self.nodes = None
		self.model = None
		super().destroy()

	### Persistence ######################################################################

	def saveFile(self):
		self.container.saveFile()
# 		elem = self.serializeXML()
# 		tree = et.ElementTree(element=elem)
# 		et.indent(tree, space='	 ', level=0)
# 		tree.write(f"graphs.{app.APP_FILE_EXTENSION}", xml_declaration=True, encoding="utf-8")
		

	def serializeXML(self) -> et.Element:
		"""
		Returns the representation of this object as an Element object.
		Implementors should call *super().serializeXML()* **first** as this top-level method
		will construct the Element itself.
		"""
		elem = PO.serializeXML(self) # selective "super()"
		elem.set("model", self.model.idString)
		elem.set("modelEditor", str(self.isModelEditor))
		elem.set("hiddenCategories", str(list(self.hiddenCategories)))
		elem.set("geometry", self.winfo_toplevel().geometry())
		
		# save nodes
		nodes = et.Element("nodes")
		elem.append(nodes)
		for n in self.nodes:
			x = n.serializeXML()
			nodes.append(x)
			
		# save relations
		rels = et.Element("relations")
		elem.append(rels)
		for r in self.relations:
			x = r.serializeXML()
			rels.append(x)
			
		return elem

	@classmethod
	def getArgs(cls, elem: et.Element, addrServer:AddrServer) -> Tuple[List[Any], Dict[str, Any]]:
		args = []
		kwargs = dict()
		args.append(None) # TODO: should we be passing a Window here?
		
		container = addrServer.idLookup(app.CONTAINER_ID)
		args.append(container)

		model = elem.get("model")
		model = addrServer.idLookup(model) if model!=None and model!="" else None
		args.append(model)
		
		idStr = elem.get('id')
		id = IDServer.getLocalID(idStr) if idStr else None
		kwargs["_id"] = id
		kwargs["idServer"] = container
		
		hiddenCategories = elem.get("hiddenCategories")
		if hiddenCategories is not None:
			kwargs["hiddenCategories"] = literal_eval(hiddenCategories)
			
		geometry = elem.get("geometry")
		if geometry is not None:
			kwargs["windowGeometry"] = geometry
		
		return args, kwargs
	
	def unserializeXML(self, elem: et.Element, addrServer:AddrServer):
		"""
		This object is partially constructed, but we need to restore this class's bits.
		Implementors should call *super().xmsRestore()* at some point.
		"""
		self.readingPersistentStore = True
		try:
			super().unserializeXML(elem, addrServer)
			e = elem.get("modelEditor")
			self.isModelEditor = literal_eval(e) if e!=None else True
			nodes = elem.find("nodes")
			for subelem in nodes.iterfind("*"):
				try:
					node = self.makeObject(subelem, addrServer, VNode) # The vnodes will enter themselves into self.nodes
				except Exception as ex:
					self.logger.write(f'Could not create VNode {subelem.get("id")}: {type(ex).__name__}("{ex}"). Could be removal of {subelem.get("model")} in the model.', level="warning", exception=ex)
			# Now let the nodes actually draw themselves.
			for n in self.nodes:
				n._post__init__(addrServer)

			rels = elem.find("relations")
			for subelem in rels.iterfind("*"):
				try:
					node = self.makeObject(subelem, addrServer, VRelation) # The vnodes will enter themselves into self.nodes
				except AttributeError as ex:
					self.logger.write(f'Could not create VRelation {subelem.get("id")}: {type(ex).__name__}("{ex}") Could be removal of {subelem.get("model")} in the model.', level='warning', exception=ex)
			# in case there were any address-lookup faults, give the relations a chance to fix it.
			deletions = []
			for r in self.relations:
				try: # we might have created a vrelation with one of the terminals on an object deleted in the model
					r._post__init__(addrServer)
				except KeyError as ex:
					deletions.append(r)
			for d in deletions:
				self.logger.write(f'Deleting VRelation {d.idString} because one of its terminals was probably deleted in the model.', level='warning')
				d.delete()
			
			for n in self.nodes+self.relations:
				n.adjustPos()
		finally:	
			self.readingPersistentStore = False


	### Event handling ###################################################################

	def onRightMouse(self, event):
		if self.isEventHandled(event):
			self.removeEventHandled(event)
			return None
		x, y = event.x, event.y
		bgMenu = self.makeMenu(event)
		bgMenu.post(event.x_root, event.y_root)
		return bgMenu

	def onB1_ButtonRelease(self, event):
		if self.isEventHandled(event):
			self.removeEventHandled(event)
			return None
		self._scrolling = False
		if self._makingRelationFrom is not None:
			self.delete(self._makingRelationFrom.lineID)
			ids = self.find("closest", self.canvasx(event.x), self.canvasy(event.y)) # find selected objects
#			self.logger.write(f"graphs making relation for {ids}", level='info')
			if isinstance(self._makingRelationFrom.node, VRelation):
				typeList = self.relations
			elif isinstance(self._makingRelationFrom.node, VNode):
				typeList = self.nodes
			else:
				typeList = []
			item = None
			for n in typeList:
				for id in ids:
					tags = self.gettags(id)
					if n.tag in tags:
						item = n # this object is selected
						break
				else:
					continue  # only executed if the inner loop did NOT break
				break  # only executed if the inner loop DID break
			if item is not None:
				self.logger.write(f"making relation from {self._makingRelationFrom.node} to {item} of type {self._makingRelationFrom.type}.", level="debug")
				self.makeRelation(self._makingRelationFrom.node, item, self._makingRelationFrom.type)
			else:
				self.logger.write("Relation's toNode must match the being a node/relation with the from Node", level='error')
			self._makingRelationFrom = None
			return
		if self._selectionBoxInfo is not None:
			bb = self.coords(self._selectionBoxInfo[0])
			ids = self.find("overlapping", bb[0], bb[1], bb[2], bb[3]) if len(bb)==4 else []
			for s in self.selected.copy(): # unselect everything
				s.selected(False)
			for id in ids:
				for n in self.nodes+self.relations:
					if n._shape.id == id:
						n.selected(True, _multi=True)
			self.delete(self._selectionBoxInfo[0])
			self.selectionBoxInfo = None
		
			
	def onMotion(self, event):
		if self.isEventHandled(event):
			self.removeEventHandled(event)
			return None
		if self._makingRelationFrom is not None:
			self.coords(self._makingRelationFrom.lineID, 
						flattenPairs([self.viewToWindow(self._makingRelationFrom.node.centerPt()), 
											(self.canvasx(event.x), self.canvasy(event.y))]))
			
	def onButton_1(self, event):
		if self._makingRelationFrom is not None: return
		if self.isEventHandled(event):
			self.removeEventHandled(event)
			return None
		if s_SHIFT(event.state):
			self._scrolling = True
			self.scan_mark(event.x, event.y)
			return
		for s in self.selected.copy(): # unselect everything
			s.selected(False)
		self._selectionBoxInfo = [self.create_rectangle(
				self.viewToWindow(event.x, event.y, event.x, event.y),
				fill="", width=3, outline="blue"), event.x, event.y, False]

		
	def onB1_Motion(self, event):
		if self.isEventHandled(event):
			self.removeEventHandled(event)
			return None
		if self._scrolling:
			self.scan_dragto(event.x, event.y, gain=1)
			return
		if self._selectionBoxInfo is not None:
			self._selectionBoxInfo[3] = True
#			bb = self.coords(self._selectionBoxInfo[0])
			bb = normalizeRect([self._selectionBoxInfo[1], self._selectionBoxInfo[2], event.x, event.y])
			self.coords(self._selectionBoxInfo[0], bb[0], bb[1], bb[2], bb[3])
		
	def onMouseWheel(self, event):
		if self.isEventHandled(event):
			self.removeEventHandled(event)
			return None
		self.yview_scroll(int(event.delta), 'units')
		
	def onShift_MouseWheel(self, event):
		if self.isEventHandled(event):
			self.removeEventHandled(event)
			return None
		self.xview_scroll(int(event.delta), 'units')
		
	def zoom(self, scale:float=1.0, delta=False):
		"""
		:param scale: the absolute scale, where 1.0 is "no scaling", unless *delta* is true, in which
						case, multiplier for the current scale (so numbers like 0.9 and 1.1 make sense).
		:param delta: True to do relative scaling, False to do absolute scaling. 
		"""
		oldScale = self._scale
		if delta:
			self._scale *= scale
		else:
			self._scale = scale
		self.scale("all", 0, 0, self._scale/oldScale, self._scale/oldScale)
		for child_widget in self.find_withtag("text"):
			self.itemconfigure(child_widget, font=(self._fontFace, int(self._fontSize*self._scale)))
		bb = list(self.bbox("all"))
		bb = [0, 0, bb[2]+800, bb[3]+600]
		self.configure(scrollregion=bb)


	def setNewNodeDisplaySelectionPolicy(self, func:Optional[Callable[[MObject], bool]]=None):
		"""
		Changes the policy on displaying newly created model objects are selected for display.
		By default (argument is *None*), the policy is
		*lamdda mObj: not self.categories.isCategory(mObj, self.hiddenCategories)*, 
		"display everything new unless it is in a hidden category".
		:return: The previous policy function
		"""
		oldPolicy = self.newNodeDisplaySelectionPolicy
		if func is None:
			self.newNodeDisplaySelectionPolicy = lambda mObj: not self.categories.isCategory(mObj, self.hiddenCategories)
		else:
			self.newNodeDisplaySelectionPolicy = func
		return oldPolicy
			
	def notifyModelChanged(self, modelObj, modelOperation:str):
		"""Handles modelOperations: "add node", "add rel", "del node", "del rel"""
		if modelOperation in ["add node", "add rel"]:
			if self.newNodeDisplaySelectionPolicy(modelObj):
				vObject = self.findViewObjectForModelObject(modelObj)
				if vObject is None:
					self.makeViewObjectForModelObject(modelObj)
		elif modelOperation == "del node" or modelOperation == "del rel":
			vObject = self.findViewObjectForModelObject(modelObj)
			if vObject is not None:
				vObject.delete()
		else:
			raise TypeError(f'TGView.notifyModelChanged({modelObj}, "{modelOperation}"): Unknown model operation "{modelOperation}".')

	### Utility ##########################################################################
	
	def viewToWindow(self, *args) -> List[float]:
		"""
		:param args: Either a single list argument or multiple float parameters. In either case there 
					must be an even number of items, taken as x,y pairs.
		:return: A list converted coordinates where the evens are x coordinates and the odds are y coordinates
					converted from view to window coordinates. 
		"""
		length = len(args)
		if len(args) == 1 and isinstance(args[0], Iterable):
			args = args[0]
		assert len(args)%2 == 0, f'args = {args}'
		ret = []
		for n in args:
			ret.append(n*self._scale)
		return ret
	
	def windowToView(self, *args) -> List[float]:
		"""
		:param args: Either a single list argument or multiple float parameters. In either case there 
					must be an even number of items, taken as x,y pairs.
		:return: A list converted coordinates where the evens are x coordinates and the odds are y coordinates
					converted from window to view coordinates. 
		"""
		length = len(args)
		if len(args) == 1 and isinstance(args[0], Iterable):
			args = args[0]
		assert len(args)%2 == 0, f'args = {args}'
		ret = []
		for n in args:
			ret.append(n/self._scale)
		return ret
	
	def makeMenu(self, event=None):
		x = 0
		y = 0
		if event!=None:
			x = event.x
			y = event.y
		bgMenu = tk.Menu(self)
		
		# "new node" menu
		if self.isModelEditor:
			newNodeMenu = tk.Menu(self)
			types = []
			for t in (t for t in self.model._nodes if t.attrs['type']):
				types.append(t)
			# TODO: sort menu?
			for t in types:
				newNodeMenu.add_command(label=t.attrs['label'], \
					command=lambda x=x, y=y, t=t: self.queueNewNode(x, y, t))
			bgMenu.add_cascade(label="new node", menu=newNodeMenu)
			bgMenu.add_separator()
		
		bgMenu.add_command(label="show all", command=self.showAllModel)
		
		# "hide/enable" menu
		hideEnableMenu = tk.Menu(self)
		for name in self.categories.keys():
			hideEnableMenu.add_command(label=f'{"enable" if name in self.hiddenCategories else "hide"} {name}',
					command = lambda n=name: self.toggleCategory(n))
		bgMenu.add_cascade(label="hide/enable", menu=hideEnableMenu)
		bgMenu.add_separator()
		
		# "local layout" menu
		localLayoutsMenu = tk.Menu(self)
		self.suppressLocalLayoutButton = tk.BooleanVar(value=self._suppressLocalLayout)
		self.radio = tk.StringVar(value=self.localLayoutName)
		for name, obj in self.layoutObjects.items():
			if obj.isLocal():
				localLayoutsMenu.add_radiobutton(label=name, variable=self.radio, value=name, \
						command=lambda lo=obj, name=name: self.setLocalLayout(lo, name=name))
		localLayoutsMenu.add_separator()
		localLayoutsMenu.add_checkbutton(label="suppress autolayout", variable=self.suppressLocalLayoutButton, 
				onvalue=True, offvalue=False, 
				command=lambda val=not self.suppressLocalLayout(): self.suppressLocalLayout(val))
		bgMenu.add_cascade(label="local layout", menu=localLayoutsMenu)
		
		# "global layout" menu
		layoutsMenu = tk.Menu(self)
		for name, obj in self.layoutObjects.items():
			if obj.isGlobal() and not obj.isLocal():
				layoutsMenu.add_command(label=name, command=obj)
		layoutsMenu.add_separator()
		for name, obj in self.layoutObjects.items():
			if obj.isGlobal() and obj.isLocal():
				layoutsMenu.add_command(label=name, command=obj)
		bgMenu.add_cascade(label="global layout", menu=layoutsMenu)
		bgMenu.add_command(label="reset scroll region", command=self.setScrollRegion)
		
		zoommenu = tk.Menu(bgMenu)
		zoommenu.add_command(label="Normal Size", command=self.zoom)
		zoommenu.add_command(label="Zoom In", command=lambda: self.zoom(1.1, delta=True))
		zoommenu.add_command(label="Zoom Out", command=lambda: self.zoom(0.9, delta=True))
		zoommenu.add_separator()
		zoommenu.add_command(label="200%", command=lambda: self.zoom(2.0))
		zoommenu.add_command(label="150%", command=lambda: self.zoom(1.5))
		zoommenu.add_command(label="75%", command=lambda: self.zoom(0.75))
		zoommenu.add_command(label="50%", command=lambda: self.zoom(0.5))
		zoommenu.add_command(label="25%", command=lambda: self.zoom(0.25))
		bgMenu.add_cascade(label="Zoom", menu=zoommenu)
		
		return bgMenu
	
	def toggleCategory(self, name:str):
		if name in self.hiddenCategories:
			self.hiddenCategories.remove(name)
		else:
			self.hiddenCategories.add(name)
			# nodes should be deleted ahead and separately from relations and deleting nodes might automattically delete relations
			for n in [x for x in self.nodes if self.categories.isCategory(x.model, self.hiddenCategories)]:
				n.delete()
			for n in [x for x in self.relations if self.categories.isCategory(x.model, self.hiddenCategories) and x.model.attrs['type']]:
				n.delete()
			for n in [x for x in self.relations if self.categories.isCategory(x.model, self.hiddenCategories)]:
				n.delete()
		
	def queueNewNode(self, x, y, t):
		self.newNodeCoords = (x, y)
		mNode = MNode(self.model, t, idServer=self.model)
		mNode.attrs.edit(self, title=f'New subtype of {t.idString} "{t.attrs["label"]}"')

	def isEventHandled(self, event):
		return eventEqual(event, self._eventHandled)

	def addEventHandled(self, event):
		self._eventHandled = event

	def removeEventHandled(self, event):
		self._eventHandled = None
		
	@property
	def localLayout(self):
		return self.doNothing if self._suppressLocalLayout else self._localLayout

	def setLocalLayout(self, layout, name=None):
		if layout is not None:
			assert isinstance(layout, layouts.LayoutHieristic)
			self._localLayout = layout
			self.localLayoutName = "" if name is None else name
		return self.localLayout
		
	def doNothing(self, *args): pass

	def suppressLocalLayout(self, suppress=None):
		if suppress is not None:
			if isinstance(suppress, str):
				self._suppressLocalLayout = suppress.lower() in ['true', 't', 'yes', 'y', 'on']
			else:
				assert isinstance(suppress, bool)
				self._suppressLocalLayout = suppress
		return self._suppressLocalLayout
		
	### Operations #######################################################################
	
	def makeViewObjectForModelObject(self, mObject:MObject, atPoint:Optional[Tuple[float, float]]=None):
		# make certain we don't make a duplicate
		vObj = self.findViewObjectForModelObject(mObject)
		if vObj is not None:
			return vObj
			
		if isinstance(mObject, Isa):
			return VIsa(self, model=mObject, idServer=self)
		elif isinstance(mObject, MRelation):
			return VRelation(self, model=mObject, idServer=self)
		else:
			assert isinstance(mObject, MNode), f'TGView.makeViewObjectforModelObject(): unexptect model object type: {type(mObject).__name__}.'
			sizex = mObject.attrs["minSize"]
			sizey = int(sizex * mObject.attrs["aspectRatio"]) 
			if atPoint is None:
				return VNode(self, self.newNodeCoords[0], self.newNodeCoords[1], 
						self.newNodeCoords[0] + sizex, 
						self.newNodeCoords[1] + sizey, 
						model=mObject, idServer=self)
			else:
				return VNode(self, atPoint[0], atPoint[1], atPoint[0]+sizex, 
						atPoint[1]+sizey, model=mObject, idServer=self)
		assert False, "TGView.makeViewObjectForModelObject(): Unexpected code executing."
		
	def findViewObjectForModelObject(self, mObject:MObject):
		if isinstance(mObject, MNode):
			for vnode in self.nodes:
				if vnode.model is mObject: # already displayed?
					return vnode
			return None
		if isinstance(mObject, MRelation):
			for vrel in self.relations:
				if vrel.model is mObject: # already displayed?
					return vrel
			return None
		assert False, "We should never get here."

	def showAllModel(self):
		x = 10
		y = 10
		sizex = self.model.topNode.attrs["minSize"]
		sizey = int(sizex * self.model.topNode.attrs["aspectRatio"]) 
		grid = (sizex*2, sizey*2) 
		numNodes = len(self.model._nodes) - len(self.nodes)
		gridCount = int(sqrt(numNodes))
		blockSize = gridCount * grid[1] + y
		for mnode in self.model._nodes:
			if self.categories.isCategory(mnode, self.hiddenCategories):
				continue
			vObj = self.findViewObjectForModelObject(mnode)
			if vObj is None and not self.categories.isCategory(mnode, self.hiddenCategories):
				n = self.makeViewObjectForModelObject(mnode, atPoint=(x,y))
				if y<blockSize:
					y += grid[1]
				else:
					x += grid[0]
					y = 10
				self.localLayout(n)
		for mrel in self.model._relations:
			if self.categories.isCategory(mrel, self.hiddenCategories) or \
					self.categories.isCategory(mrel.toNode, self.hiddenCategories) or \
					self.categories.isCategory(mrel.fromNode, self.hiddenCategories):
				continue
			vObj = self.findViewObjectForModelObject(mrel)
			if vObj is None:
				try:
					r = self.makeViewObjectForModelObject(mrel)
					self.localLayout(r)
				except Exception as ex:
					self.logger.write(f'Could not instantiate VObject for {type(mrel).__name__} {mrel.idString} "{mrel.attrs["label"]}": {type(ex).__name__}("{ex}")', level='warning', exception=ex)
					
	def makeRelationFrom(self, node:VNode, typ:Optional[MObject]=None):
		if typ is None or isinstance(typ, MNode) or isinstance(typ, MRelation):
			lineID = self.create_line(
				self.viewToWindow(flattenPairs([node.centerPt(), node.centerPt()])),
				fill="cyan", width=3, arrow=tk.LAST)
			self._makingRelationFrom = TGView.makeRelationData(node, typ, lineID)
		else:
			raise TypeError(f'TGView.makeRelationFrom(): "typ" argument must be a model object; got object of class {type(typ).__name__}.')
	
	def makeRelation(self, fromNode:VNode, toNode:VNode, typ:MObject):
		if      isinstance(fromNode, VRelation) and not isinstance(toNode, VRelation) or \
			not isinstance(fromNode, VRelation) and     isinstance(toNode, VRelation):
			tk.messagebox.showerror(app.APP_LONG_NAME, "Relations must be either between nodes or between relations only.")
			return
		if typ and not isinstance(typ, MRelation):
			tk.messagebox.showerror(app.APP_LONG_NAME, f'Relation typ {typ.attrs["label"]} must be a relation.')
			return
		try:
			if isinstance(typ, Isa):
# 				vrelations.VIsa(self, fromNode, toNode, idServer=self, typ=typ) # create the view relation and the model relation
				Isa(self.model, fromNode.model, toNode.model, idServer=self.model)
			else:
# 				vrelations.VRelation(self, fromNode, toNode, idServer=self, typ=typ) # create the view relation and the model relation
				MRelation(self.model, fromNode.model, toNode.model, typ=typ, idServer=self.model)
		except Exception as ex:
			tk.messagebox.showerror(app.APP_LONG_NAME, f'{type(ex).__name__}: {ex}')
# 			raise ex			
		
import tygra.layout as layouts

root = None

if __name__ == "__main__":

## Runs but causes a fault later on... 
# 	if sys.platform.startswith('darwin'):
# 		try:
# 			print('installing icon')
# 			from Cocoa import NSApplication, NSImage
# 		except ImportError:
# 			print('Unable to import pyobjc modules')
# 		else:
# 			ns_application = NSApplication.sharedApplication()
# 			logo_ns_image = NSImage.alloc().initByReferencingFile_('./tg.icns')
# 			ns_application.setApplicationIconImage_(logo_ns_image)
# 			print('installed icon')

	root = TygraContainer(f"typedgraphs.{app.APP_FILE_EXTENSION}" if os.path.isfile(f"typedgraphs.{app.APP_FILE_EXTENSION}") else None)
	root.mainloop()
