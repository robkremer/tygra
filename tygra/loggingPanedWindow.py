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

import tkinter as tk
from tkinter import ttk
from typing import Any, Optional, Type, Union, Union, Tuple, Callable, Iterable, TypeVar, Generic, List, Dict
from io import TextIOWrapper
import sys
import os
import traceback
from tygra.util import play
import tygra.util as util
from pickle import NONE
import inspect

class LoggingPanedWindow(tk.PanedWindow):
	"""
	A (tkinter.PanedWindow) with two panes: above, and application widget according the
	*frame* parameter of the constructor, and below, a disabled text widget which is used
	by this class's various service methods to display messages such as logging info:
	
		+-------------------------+
		|                         |
		|    application widget   |
		|                         |
		+-------------------------+
		|   logging text widget   |
		+-------------------------+		
	"""

	class StdoutRedirector(object):
		def __init__(self, owner, tag, stdOutput):
			self.owner = owner
			self.tag = tag
			self.stdOutput = stdOutput

		def write(self, string:str):
			string = string.rstrip()
			if len(string) == 0: return
			self.stdOutput.write(string+"\n")
			self.owner._prep()
			self.owner.textArea.insert('end', string, self.tag)
			self.owner._finish()

		def flush(self):
			pass

	@property
	def maxLevelStr(self):
		return LoggingPanedWindow.levelToTag[self.maxLevel]
	
	@maxLevelStr.setter
	def maxLevelStr(self, val:str):
		self.maxLevel = self._getLevel(val)

	def __init__(self, parent, frame=lambda p: tk.Frame(p), 
				maxLines:int=24, visibleLines:int=2, logFiles:List[str]=None, 
				useStderr:bool=True, maxLevel:int=3, fixedAppFrame:bool=False, 
				captureStdOutput:bool=True, 
				soundError:Optional[str]='/System/Library/Sounds/Sosumi.aiff', 
				**kwargs):
		"""
		:param parent: The parent window or frame.
		:param frame: A function taking one argument (this *LoggingPanedWindow* instance 
						itself, as the parent of the application window) which must return
						a widget that acts as the application window. This will be the
						*self.appFrame* variable of the new *LoggingPanedWindow*. [default:
						lambda p: ttk.Frame(p)]
		:type frame: 	Callable[[Self], tk.Widget]
		:param maxLines: The maximum number of lines the text widget frame will maintain.
						User 0 for "infinite" [default: 24]
		:param visibleLines: the number of lines the text widget will initially display.
						[default: 2]
		:param logFiles: A open-for-write file object (or objects), like sys.stdout, 
						to write messages to. May be an open-file object, or a list of
						open-file objects. [default: None]
		:param stderr:	bool. If *True*, and sys.stdout is in *logFiles*, then sys.stderr 
						will be used for error-level messages. [default: True]
		:param maxLevel: The maximum level to print. Cannot be less than 0 (normal)
		:param captureStdOutput: Capture any output to *sys.stdout* and *sys.stderr* and
						display it before forwarding it back to *sys.stdout* and *sys.stderr*.
		:param soundError: An sound file to play when an error level message occurs.
		:param \*\*kwargs: An arguments *dict* to passed to the *tk.PanedWindow* constructor.
		"""
		# fix up kwargs to contain the necessary defaults and create the PanedWindow (super).
		if "orient" not in kwargs: kwargs["orient"] = tk.VERTICAL
		if "showhandle" not in kwargs: kwargs["showhandle"] = False
		if "sashwidth" not in kwargs: kwargs["sashwidth"] = 6
		if "bd" not in kwargs: kwargs["bd"] = 4
		if "bg" not in kwargs: kwargs["bg"] = "grey"
		if "borderwidth" not in kwargs: kwargs["borderwidth"] = 0
		super().__init__(parent, **kwargs)
		
		# set up the class's properties (mostly from parameters...)
		self.maxLines = maxLines
		self.visibleLines = visibleLines
		self.useStderr = useStderr
		self.maxLevel = 3
		self.setMaxLevel(maxLevel)
		self.soundError = soundError
		self.lastTraceback = "<No traceback recorded>"
		self.tracebackCount = 0
		self.fixedAppFrame = fixedAppFrame
		self.appFrame = None

		# set up the internal frames within the PanedWindow.
		self.textArea = tk.Text(self, state='disabled', wrap='none', width=80, height=visibleLines, borderwidth=0)#ttk.Labelframe(self.panedWindow, text='Pane1')#, width=100, height=100)
		self.textArea.pack(fill=tk.BOTH, side=tk.TOP, expand=True)
		self.pack(fill=tk.BOTH, expand=True)
		self.textArea.tag_config("traceback"    , foreground="purple", font="Courier 0")
		self.textArea.tag_config("error"        , foreground="red")
		self.textArea.tag_config("normal"       , foreground="black")
		self.textArea.tag_config("warning"      , foreground="brown")
		self.textArea.tag_config("informational", foreground="grey")
		self.textArea.tag_config("debug"        , foreground="green")
		self.textArea.tag_config("errorTag"     , foreground="red"  , font=self.textArea.cget("font")+" 0 bold")
		self.textArea.tag_config("warningTag"   , foreground="brown", font=self.textArea.cget("font")+" 0 bold")
		self.textArea.tag_config("stdout"       , foreground="black", font="Courier 0 italic")
		self.textArea.tag_config("stderr"       , foreground="red"  , font="Courier 0 bold italic")

		stretch = 'always' if fixedAppFrame else 'never'
		sticky = 'news' if fixedAppFrame else 'new'
		self.add(self.textArea, stretch=stretch, sticky=sticky)
		self.paneconfigure(self.textArea, stretch=stretch)

		self.setAppFrame(None if frame is None else frame(self))
		
		# deal with capturing stdout and stderr (param captureStdOutput)
		self.realStdout = sys.stdout
		self.realStderr = sys.stderr
		if captureStdOutput and sys.stdout is sys.__stdout__:
			sys.stdout = LoggingPanedWindow.StdoutRedirector(self, "stdout", self.realStdout)
			sys.stderr = LoggingPanedWindow.StdoutRedirector(self, "stderr", self.realStderr)
		
		# deal with log files
		if logFiles is None:
			self.logFiles = []
		else:
			if not isinstance(logFiles, list): self.logFiles = [logFiles]
		# check type and writability of items in the logFiles parameter
		bad = []
		for f in self.logFiles:
			if not isinstance(f, TextIOWrapper):
				if not isinstance(f, LoggingPanedWindow.StdoutRedirector):
					self.write(f'Unaccepted type "{type(f).__name__}" for "logFiles" argument.', level=-1)
				bad.append(f)
				continue
			if not f.writable():
				self.write(f'Got a file in "logFiles" argument that does not appear to be writable.', level=-1)
				bad.append(f)
		for f in bad: self.logFiles.remove(f)
		
	def delete(self):
		sys.stdout = self.realStdout
		sys.stderr = self.realStderr
		for i in range(len(self.logFiles)):
			self.logFiles[i] = None
		self.logFiles = None
		
	levelToTag = {	-1: "error",
					 0: "normal",
					 1: "warning",
					 2: "informational",
					 3: "debug"}

	def setAppFrame(self, frame:Optional[tk.Frame]):
		if self.appFrame is not None:
			self.forget(self.appFrame)
			self.appFrame.destroy()
		
		if frame is not None:
			self.appFrame = frame
		else:
			self.appFrame = tk.Frame(self)
		self.appFrame.pack(fill=tk.BOTH if self.fixedAppFrame else tk.BOTH, side=tk.TOP, expand=False if self.fixedAppFrame else True)
		
		stretch = 'never' if self.fixedAppFrame else 'always'
		sticky = 'new' if self.fixedAppFrame else 'news'
		self.add(self.appFrame, before=self.textArea, stretch=stretch, sticky=sticky)#'always', 'first', 'last', 'middle', and 'never'.
		self.paneconfigure(self.appFrame, stretch=stretch)
		
	@staticmethod
	def _getLevel(obj):
		if isinstance(obj, int): 
			if obj < 0:  return -1
			if obj > 3:  return 3
			return obj
		if isinstance(obj, str):
			obj = obj.lower()
			if obj == "error":   return -1
			if obj == "normal":  return 0
			if obj == "warning": return 1
			if obj == "informational"[0:len(obj)]: return 2
			if obj == "debug":   return 3
		return 0
		
	def setMaxLevel(self, level:Union[str,int]=2) -> int:
		"""
		Sets the maximum error level to print and returns the previous level. Error and
		normal messages are always printed, so *maxLevel* cannot be less than 1. """
		ret = self.maxLevel
		level = self._getLevel(level)
		if level < 0:
			self.write("Cannot set level at < 0 (normal). Using 0.", level="error")
			level = 0
		self.maxLevel = level
		return ret
		
	def _writeTraceback(self, event, tbString=None):
		self._prep()
		self.textArea.insert('end', str(tbString), ('traceback',))		
		self._finish()

	def _prep(self):
		numlines = int(self.textArea.index('end - 1 line').split('.')[0])
		self.textArea['state'] = 'normal'
		if numlines >= self.maxLines:
			self.textArea.delete('1.0', f'{self.maxLines-numlines+2}.0')
		if self.textArea.index('end-1c')!='1.0':
			self.textArea.insert('end', '\n')
			
	def _finish(self):
		self.textArea.see('end -1 lines')
		self.textArea['state'] = 'disabled'
		top = self.winfo_toplevel()
		top.update_idletasks()
		top.update()		
				
	def write(self, msg, level:Union[str,int]=0, exception:Optional[Exception]=None):
		"""
		:param msg: The message to write to the logging window (and anything else this
				object might be writing to).
		:param level: A severity level for this message which may be displayed as a font
				color or font change. May be a string ("error" "normal", "warning", "informational", "debug") or
				an *int* (correspondingly -1 (or -ve), 0, 1, 2, 3).
		"""
		level = self._getLevel(level) # level is now guaranteed to be an int
		if level > self.maxLevel:
			return
			
		self._prep()
		
		if   level == -1: 
			self.textArea.insert('end', "ERROR: ", ("errorTag",))
			prefix = "***ERROR***: "
			if self.soundError is not None:
				play(self.soundError)
		elif level ==  1:
			self.textArea.insert('end', "WARNING: ", ("warningTag",))
			prefix = "*WARNING*: "
		elif level ==  3:
			self.textArea.insert('end', "DEBUG: ", ("debug",))
			prefix = "DEBUG: "
		else:
			prefix = ""
			
		method = "" if level in [0,2] else (util.getCallerIdInfoStr()+": ")
		
		output = f'{prefix}{msg}'
		
		if exception is not None:
			exc_type, exc_obj, exc_tb = sys.exc_info()
			fname = os.path.split(exc_tb.tb_frame.f_code.co_filename)[1]
# 			print(exc_type, fname, exc_tb.tb_lineno)
			self.lastTraceback = traceback.format_exc()
			m = f'\n  Exception {type(exception).__name__}: {exception}, in file {fname}, line {exc_tb.tb_lineno}.'
			output += m
			msg += m

		self.textArea.insert('end', f'{msg}', (LoggingPanedWindow.levelToTag[level],))

		if exception is not None:
			self.tracebackCount += 1
			tracebackTag = "tracebackLink"+str(self.tracebackCount)
			tracebackCallback = lambda e, tbString=self.lastTraceback: self._writeTraceback(e, tbString)
			self.textArea.tag_config(tracebackTag, foreground="blue")
			self.textArea.tag_bind(tracebackTag, "<Button-1>", tracebackCallback)
			self.textArea.insert('end', ' [traceback]')
			self.textArea.tag_add(tracebackTag, "end-11c", "end-2c")
			
		if len(method) > 0:
			indent = "    " if exception is not None else "  "
			self.textArea.insert('end', f'\n{indent}in {method}', (LoggingPanedWindow.levelToTag[level],))

		self._finish()
				
		# write out to any logfiles
		for f in self.logFiles:
			if (f is sys.stdout or f is self.realStdout) and level<0:
				f = self.realStderr
			indent = "    " if exception is not None else "  "
			if len(method) > 0:
				output += f'\n{indent}in {method}'
			f.write(f'{output}\n')
			if exception is not None:
				f.write(f'{self.lastTraceback}\n')
		
