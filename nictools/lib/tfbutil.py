#! /usr/bin/env python

import sys

# Utility functions and parameters for temp_from_bias

QUIET = 0 # verbosity levels
VERBOSE = 1
VERY_VERBOSE = 2   
                                                                                
# default values
verbosity = VERBOSE
hdr_key = "TFBT"
err_key = "TFBE"
edit_type = "RAW" 
nref_par = "/grp/hst/cdbs/nref/"
noclean = False
force = None

__version__ = "1.3"

def all_printMsg( message, level=VERBOSE):

    if verbosity >= level:     
      print message
      sys.stdout.flush()

def printMsg( message, level=QUIET):

    if verbosity >= level:
      print message
      sys.stdout.flush()

def setVerbosity( verbosity_level):
    """Copy verbosity to a variable that is global for this file.        
       argument: verbosity_level -  an integer value indicating the level of verbosity
    """
                                                                                
    global verbosity
    verbosity = verbosity_level

def checkVerbosity( level):
    """Return true if verbosity is at least as great as level."""

    return (verbosity >= level)

def setHdr_key( hdr_key_value): 
    """Copy hdr_key to a variable that is global for this file.        
       argument: hdr_key -  a string for the keyword name to write
    """
                                                                                
    global hdr_key
    hdr_key = hdr_key_value

def setErr_key( err_key_value): 
    """Copy err_key to a variable that is global for this file.        
       argument: err_key -  a string for the keyword for the error estimate
    """
                                                                                
    global err_key
    err_key = err_key_value

def setEdit_type_key( edit_type_value): 
    """Copy edit_type_key to a variable that is global for this file.        
       argument: edit_type_key -  a string for the keyword name to write
    """
                                                                                
    global edit_type
    edit_type = edit_type_value

def setNoclean( noclean_value): 
    """Copy no_clean to a variable that is global for this file.        
       argument: no_clean - string that is either True or False
    """
                                                                                
    global noclean
    noclean = noclean_value

def setNref( nref_value): 
    """Copy nref to a variable that is global for this file.        
       argument: nref - string for name of directory containing nonlinearity file 
    """
                                                                                
    global nref
    nref = nref_value

def setForce( force_value ):
    """Copy force to a variable that is global for this file.        
       argument: force - string that is either None, Q, B, or S
    """
                                                                                
    global force
    force = force_value

