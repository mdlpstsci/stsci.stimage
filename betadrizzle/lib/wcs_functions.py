import os,copy
import numpy as np
from numpy import linalg

from stwcs import wcsutil
from stwcs.distortion import utils

from pytools import fileutil,asnutil
import util
import imageObject
import stwcs
import pywcs
from stwcs import distortion
from stwcs.distortion import coeff_converter,utils


DEFAULT_WCS_PARS = {'ra':None,'dec':None,'psize':None,'orient':None,
                     'outnx':None,'outny':None,'crpix1':None,'crpix2':None,
                     'crval1':None,'crval2':None}


shift_kwlist = ['WSHIFT1','WSHIFT2','WROT','WSCALE']
shift_kwcomments = ['Shift in axis1 from shiftfile','Shift in axis2 from shiftfile','Rotation from shiftfile','scale change from shiftfile']

WCSEXTN_NAME = 'WCSCORR'
# Default mapping function based on PyWCS 
class WCSMap:
    def __init__(self,input,output,origin=1):
        # Verify that we have valid WCS input objects
        self.checkWCS(input,'Input')
        self.checkWCS(output,'Output')

        self.input = input
        self.output = copy.deepcopy(output)
        #self.output = output
        
        self.origin = origin
        self.shift = None
        self.rot = None
        self.scale = None

    def checkWCS(self,obj,name):
        try:
            assert isinstance(obj, pywcs.WCS)
        except AssertionError:
            print name +' object needs to be an instance or subclass of a PyWCS object.'
            raise

    def applyShift(self,imageObject):
        """ This method pre-computes the correction which needs to be 
            applied to this entire image based on the information 
            stored in any existing WCSCORR extension in the input image.
            
            This method ALWAYS gets called by 'run_driz()' to insure that
            any shifts included in the image are applied.
        """
        self.shift,rot,scale = applyHeaderlet(imageObject,self.input,self.output,extname=WCSEXTN_NAME)
        self.rot = rot
        self.scale = scale
        if self.shift is not None:
            print '    Correcting WCSMap input WCS for shifts...'
            # Record the shift applied with the WCS, so that we can tell it
            # has been applied and not correct the WCS any further
            # Update OUTPUT WCS crpix value with shift, since it was determined
            # in (and translated to) the output frame.
            self.output.wcs.crpix -= self.shift

            # apply translated rotation and scale from shiftfile to input WCS
            self.output.rotateCD(rot)
            self.output.wcs.cd *= scale
            self.output.orientat += rot
            self.output.pscale *= scale

    def forward(self,pixx,pixy):
        """ Transform the input pixx,pixy positions in the input frame
            to pixel positions in the output frame.
            
            This method gets passed to the drizzle algorithm.
        """
        # This matches WTRAXY results to better than 1e-4 pixels.
        skyx,skyy = self.input.all_pix2sky(pixx,pixy,self.origin)
        result= self.output.wcs_sky2pix(skyx,skyy,self.origin)
        return result
    
    def get_pix_ratio(self):
        """ Return the ratio of plate scales between the input and output WCS.
            This is used to properly distribute the flux in each pixel in 'tdriz'.
        """
        return self.output.pscale / self.input.pscale
    
    def xy2rd(self,wcs,pixx,pixy):
        """ Transform input pixel positions into sky positions in the WCS provided.
        """
        return wcs.all_pix2sky(pixx,pixy,1)
    def rd2xy(self,wcs,ra,dec):
        """ Transform input sky positions into pixel positions in the WCS provided.
        """
        return wcs.wcs_sky2pix(ra,dec,1)
                    
def get_hstwcs(filename,hdulist,extnum):
    ''' Return the HSTWCS object for a given chip.
    
    '''
    hdrwcs = wcsutil.HSTWCS(hdulist,ext=extnum)
    hdrwcs.filename = filename
    hdrwcs.expname = hdulist[extnum].header['expname']
    hdrwcs.extver = hdulist[extnum].header['extver']
    
    return hdrwcs

def ddtohms(xsky,ysky,verbose=False):

    """ Convert sky position(s) from decimal degrees to HMS format."""

    xskyh = xsky /15.
    xskym = (xskyh - np.floor(xskyh)) * 60.
    xskys = (xskym - np.floor(xskym)) * 60.

    yskym = (np.abs(ysky) - np.floor(N.abs(ysky))) * 60.
    yskys = (yskym - np.floor(yskym)) * 60.

    if isinstance(xskyh,np.ndarray):
        rah,dech = [],[]
        for i in xrange(len(xskyh)):
            rastr = repr(int(xskyh[i]))+':'+repr(int(xskym[i]))+':'+repr(xskys[i])
            decstr = repr(int(ysky[i]))+':'+repr(int(yskym[i]))+':'+repr(yskys[i])
            rah.append(rastr)
            dech.append(decstr)
            if verbose:
                print 'RA = ',rastr,', Dec = ',decstr
    else:
        rastr = repr(int(xskyh))+':'+repr(int(xskym))+':'+repr(xskys)
        decstr = repr(int(ysky))+':'+repr(int(yskym))+':'+repr(yskys)
        rah = rastr
        dech = decstr
        if verbose:
            print 'RA = ',rastr,', Dec = ',decstr

    return rah,dech

def get_shiftwcs(hdulist,extname=WCSEXTN_NAME):
    """ Return the pywcs.WCS object for the WCSCORR extension which 
        contains the shift information.
    """
    # If given the name of an image instead of a PyFITS object, 
    # open the image and get the PyFITS object now.
    if isinstance(hdulist, str):
        hdulist = fileutil.openImage(hdulist)
    extnum = fileutil.findExtname(hdulist,extname)
    if extnum is None:
        # Try to interpret the input file as a reference WCS from a shiftfile
        extnum = fileutil.findExtname(hdulist,'WCS')
    # If there really is no WCS extension in the input, return None
    if extnum is None:
        return None

    extn = hdulist[extnum]
        
    hdrwcs = pywcs.WCS(header=extn.header)
    hdrwcs.orientat = extn.header['orientat']
    hdrwcs.pscale = np.sqrt(hdrwcs.wcs.cd[1,0]**2 + hdrwcs.wcs.cd[1,1]**2)*3600.0
    
    # add shift information as attributes to this WCS object
    for kw in shift_kwlist:
        hdrwcs.__dict__[kw.lower()] = extn.header[kw]
    hdrwcs.naxis1 = extn.header['npix1']
    hdrwcs.naxis2 = extn.header['npix2']
    
        
    return hdrwcs


#### Functions for applying shiftfiles
def createHeaderlets(shiftfile,clobber=True,update=True,verbose=False):
    """ Write out separate headerlets for each image in shiftfile.
        If 'update' is True, then also update the input images with the 
        headerlets as well.
    """
    # Start by reading in the shiftfile
    sdict = asnutil.ShiftFile(shiftfile)
    # Open reference WCS 
    refimg = fileutil.openImage(sdict['refimage'])
    refwcs = refimg['wcs']

    # set up shift keywords where this list corresponds one-to-one with
    # the shift values for each image in the ShiftFile object
    kwlist = shift_kwlist
    kwcomments = shift_kwcomments
    # for each image in the shiftfile,
    for img in sdict['order']:
        
        for kw,n in zip(kwlist,range(len(kwlist))):
            # Add headerlet-specific keywords to ref WCS extension
            # to record shifts, rotation and scale for 
            refwcs.header.update(kw,sdict[img][n],kwcomments[n],after='ORIENTAT')
        
        # Create name of output headerlet
        hdrname = img[:-5]+'_hdrlet.fits'
        if verbose:
            print 'Writing out headerlet: ',hdrname
        if clobber and os.path.exists(hdrname):
            # Remove file if it was already written out earlier so it can be replaced
            fileutil.removeFile(hdrname)
        refimg.writeto(hdrname)
        if update:
            addWCSExtn(refimg[1],img,verbose=verbose)
            
def removeWCSExtn(filename,extname=WCSEXTN_NAME,verbose=True):
    """ Remove all WCS extensions from file."""
    fimg = fileutil.openImage(filename,mode='update')
    if verbose:
        print 'Removing WCS shift extension from: ',img

    wcsextn = fileutil.findExtname(fimg,extname)
    while wcsextn is not None:
        del fimg[wcsextn]
        wcsextn = fileutil.findExtname(fimg,extname)
    fimg.close()
    
def addWCSExtn(wcsextn,filename, extname=WCSEXTN_NAME,verbose=True):
    """ Add WCS extension to the file, removing all previous WCS
        extensions in the process, to insure that there is only 
        1 WCS extension in the file at any one time.
    """
    # write out headerlets as new extensions to the input images
    if verbose:
        print ' Updating ',img,' with shift extension.'
    wcsextn.header.update("EXTNAME",extname)
    fimg = fileutil.openImage(filename,mode='update')
    # Remove any or all pre-existing WCSCORR extensions
    oldextn = fileutil.findExtname(fimg,extname)
    while oldextn is not None:
        del fimg[oldextn]
        oldextn = fileutil.findExtname(fimg,extname)

    fimg.append(wcsextn)
    fimg.close()
    
def applyHeaderlet(imageObject,chipwcs,outwcs,extname=WCSEXTN_NAME):
    """ Apply shift information found in headerlet extension to 
        chip in [SCI,extver]. 
    """
    hdulist = imageObject._image
    refwcs = get_shiftwcs(hdulist,extname=extname)
    if refwcs is None:
        return None,None,None

    chipname = chipwcs.filename+'["'+chipwcs.extname[0]+'",'+str(chipwcs.extname[1])+']'

    print ' Getting shift information from WCS extension to: ',chipname
    ref_center = [int(refwcs.naxis1/2) + 1, int(refwcs.naxis2/2) + 1]
    ratio = refwcs.pscale / outwcs.pscale
            
    # Now, in the ref WCS frame, find the offset of this chip from the ref WCS center
    #chip_sky = chipwcs.wcs.crval
    #ref_chip_center = refwcs.wcs_sky2pix([chip_sky[0]],[chip_sky[1]],1)
    #chip_offset = np.array([ref_chip_center[0][0]-ref_center[0], 
    #                        ref_chip_center[1][0]-ref_center[1]]) * refwcs.wscale

    # apply shift to this offset 
    #drot = fileutil.buildRotMatrix(-refwcs.wrot)
    #chip_delta = np.dot(chip_offset,drot) + [refwcs.wshift1,refwcs.wshift2] - chip_offset
    
    # Transform this offset from refwcs frame back to output wcs frame     
    chip_delta = np.array([refwcs.wshift1,refwcs.wshift2])
    delta_orient = refwcs.orientat - outwcs.orientat 
    frot = fileutil.buildRotMatrix(delta_orient)
    
    shift_center = np.dot(chip_delta,frot)*ratio
    wrot = -((360.0 - refwcs.wrot) % 360.0)
    wscale = refwcs.wscale * ratio

    return shift_center,wrot,wscale
    
    
#
# Possibly need to generate a stand-alone interface for this function.
#
#### Primary interface for creating the output WCS from a list of HSTWCS objects
def make_outputwcs(imageObjectList,output,configObj=None):
    """ Computes the full output WCS based on the set of input imageObjects
        provided as input, along with the pre-determined output name from
        process_input.  The user specified output parameters are then used to
        modify the default WCS to produce the final desired output frame.
        The input imageObjectList has the outputValues dictionary
        updated with the information from the computed output WCS. 
        It then returns this WCS as a WCSObject(imageObject) 
        instance.
    """
    if not isinstance(imageObjectList,list): 
        imageObjectList = [imageObjectList]
        
    if configObj['refimage'].strip() in ['',None]:        
        # Compute default output WCS, if no refimage specified
        hstwcs_list = []
        for img in imageObjectList:
            hstwcs_list += img.getKeywordList('wcs')
        default_wcs = utils.output_wcs(hstwcs_list)
    else:
        # Otherwise, simply use the reference image specified by the user
        default_wcs = wcsutil.HSTWCS(configObj['refimage'])
    
    # Turn WCS instances into WCSObject instances
    outwcs = createWCSObject(output,default_wcs,default_wcs,imageObjectList)
    
    # Merge in user-specified attributes for the output WCS
    # as recorded in the input configObj object.
    final_pars = DEFAULT_WCS_PARS.copy()
         
    # More interpretation of the configObj needs to be done here to translate
    # the input parameter names to those understood by 'mergeWCS' as defined
    # by the DEFAULT_WCS_PARS dictionary.
    single_step = util.getSectionName(configObj,3)
    if single_step and configObj[single_step]['driz_separate']: 
        single_pars = DEFAULT_WCS_PARS.copy()
        single_pars['ra'] = configObj['ra']
        single_pars['dec'] = configObj['dec']
        #single_pars.update(configObj['STEP 3: DRIZZLE SEPARATE IMAGES'])
        single_keys = {'outnx':'driz_sep_outnx','outny':'driz_sep_outny',
                        'rot':'driz_sep_rot', 'scale':'driz_sep_scale'}
        for key in single_keys.keys():
            single_pars[key] = configObj['STEP 3: DRIZZLE SEPARATE IMAGES'][single_keys[key]]
        ### Create single_wcs instance based on user parameters
        outwcs.single_wcs = mergeWCS(default_wcs,single_pars)
        

    final_step = util.getSectionName(configObj,7)
    if final_step and configObj[final_step]['driz_combine']: 
        final_pars = DEFAULT_WCS_PARS.copy()
        final_pars['ra'] = configObj['ra']
        final_pars['dec'] = configObj['dec']
        final_keys = {'outnx':'final_outnx','outny':'final_outny','rot':'final_rot', 'scale':'final_scale'}
        #final_pars.update(configObj['STEP 7: DRIZZLE FINAL COMBINED IMAGE'])
        for key in final_keys.keys():
            final_pars[key] = configObj['STEP 7: DRIZZLE FINAL COMBINED IMAGE'][final_keys[key]]
        ### Create single_wcs instance based on user parameters
        outwcs.final_wcs = mergeWCS(default_wcs,final_pars)
        outwcs.wcs = outwcs.final_wcs.copy()

    # Apply user settings to create custom output_wcs instances 
    # for each drizzle step
    updateImageWCS(imageObjectList,outwcs)
    
    return outwcs

#### Utility functions for working with WCSObjects
def createWCSObject(output,default_wcs,final_wcs,imageObjectList):
    """Converts a PyWCS WCS object into a WCSObject(baseImageObject) instance."""
    outwcs = imageObject.WCSObject(output)
    outwcs.default_wcs = default_wcs
    outwcs.wcs = final_wcs

    #
    # Add exptime information for use with drizzle
    #
    outwcs._exptime,outwcs._expstart,outwcs._expend = util.compute_texptime(imageObjectList)
        
    outwcs.nimages = util.countImages(imageObjectList)
     
    return outwcs

def updateImageWCS(imageObjectList,output_wcs):
    
     # Update input imageObjects with output WCS information
    for img in imageObjectList:
        img.updateOutputValues(output_wcs)
   
def restoreDefaultWCS(imageObjectList,output_wcs):
    """ Restore WCS information to default values, and update imageObject
        accordingly.
    """
    if not isinstance(imageObjectList,list): 
        imageObjectList = [imageObjectList]

    output_wcs.restoreWCS()
    
    updateImageWCS(imageObjectList,output_wcs)

def mergeWCS(default_wcs,user_pars):
    """ Merges the user specified WCS values given as dictionary derived from 
        the input configObj object with the output PyWCS object computed 
        using distortion.output_wcs().
        
        The user_pars dictionary needs to have the following set of keys:
        user_pars = {'ra':None,'dec':None,'psize':None,'orient':None,
                     'outnx':None,'outny':None,'crpix1':None,'crpix2':None,
                     'crval1':None,'crval2':None}
    """
    #
    # Start by making a copy of the input WCS...
    #    
    outwcs = default_wcs.copy()    

    # If there are no user set parameters, just return a copy of the original WCS
    merge = False
    for upar in user_pars.values():
        if upar is not None:
            merge = True
            break
        
    if not merge:
        return outwcs

    if (not user_pars.has_key('ra')) or user_pars['ra'] == None:
        _crval = None
    else:
        _crval = (user_pars['ra'],user_pars['dec'])

    if (not user_pars.has_key('psize')) or user_pars['psize'] == None:
        _ratio = 1.0
        _psize = None
        # Need to resize the WCS for any changes in pscale
    else:
        _ratio = outwcs.pscale / user_pars['psize']
        _psize = user_pars['psize']

    if (not user_pars.has_key('orient')) or user_pars['orient'] == None:
        _orient = None
        _delta_rot = 0.
    else:
        _orient = user_pars['orient']
        _delta_rot = outwcs.orientat - user_pars['orient']

    _mrot = fileutil.buildRotMatrix(_delta_rot)

    if (not user_pars.has_key('outnx')) or user_pars['outnx'] == None:
        _corners = np.array([[0.,0.],[outwcs.naxis1,0.],[0.,outwcs.naxis2],[outwcs.naxis1,outwcs.naxis2]])
        _corners -= (outwcs.naxis1/2.,outwcs.naxis2/2.)
        _range = util.getRotatedSize(_corners,_delta_rot)
        shape = ((_range[0][1] - _range[0][0])*_ratio,(_range[1][1]-_range[1][0])*_ratio)
        old_shape = (outwcs.naxis1*_ratio,outwcs.naxis2*_ratio)

        _crpix = (shape[0]/2., shape[1]/2.)

    else:
        shape = [user_pars['outnx'],user_pars['outny']]
        if user_pars['crpix1'] == None:
            _crpix = (shape[0]/2.,shape[1]/2.)
        else:
            _crpix = [user_pars['crpix1'],user_pars['crpix2']]

    # Set up the new WCS based on values from old one.
    # Update plate scale
    outwcs.wcs.cd *= _ratio
    outwcs.pscale /= _ratio
    #Update orientation
    outwcs.rotateCD(_delta_rot)
    outwcs.orientat += -_delta_rot
    # Update size
    outwcs.naxis1 =  int(shape[0])
    outwcs.naxis2 =  int(shape[1])
    # Update reference position
    outwcs.wcs.crpix =_crpix
    if _crval is not None:
        outwcs.wcs.crval = _crval

    return outwcs

def convertWCS(inwcs,drizwcs):
    """ Copy WCSObject WCS into Drizzle compatible array."""
    drizwcs[0] = inwcs.crpix[0]
    drizwcs[1] = inwcs.crval[0]
    drizwcs[2] = inwcs.crpix[1]
    drizwcs[3] = inwcs.crval[1]
    drizwcs[4] = inwcs.cd[0][0]
    drizwcs[5] = inwcs.cd[1][0]
    drizwcs[6] = inwcs.cd[0][1]
    drizwcs[7] = inwcs.cd[1][1]

    return drizwcs

def updateWCS(drizwcs,inwcs):
    """ Copy output WCS array from Drizzle into WCSObject."""
    inwcs.crpix[0]    = drizwcs[0]
    inwcs.crval[0]   = drizwcs[1]
    inwcs.crpix[1]   = drizwcs[2]
    inwcs.crval[1]   = drizwcs[3]
    inwcs.cd[0][0]     = drizwcs[4]
    inwcs.cd[1][0]     = drizwcs[5]
    inwcs.cd[0][1]     = drizwcs[6]
    inwcs.cd[1][1]     = drizwcs[7]
    inwcs.pscale = N.sqrt(N.power(inwcs.cd[0][0],2)+N.power(inwcs.cd[1][0],2)) * 3600.
    inwcs.orient = N.arctan2(inwcs.cd[0][1],inwcs.cd[1][1]) * 180./N.pi


def wcsfit(img_wcs, ref_wcs):
    """
    Perform a linear fit between 2 WCS for shift, rotation and scale.
    Based on 'WCSLIN' from 'drutil.f'(Drizzle V2.9) and modified to
    allow for differences in reference positions assumed by PyDrizzle's
    distortion model and the coeffs used by 'drizzle'.

    Parameters:
        img      - ObsGeometry instance for input image
        ref_wcs  - Undistorted WCSObject instance for output frame
    """
    # Define objects that we need to use for the fit...
    #in_refpix = img_geom.model.refpix
    wmap = WCSMap(img_wcs,ref_wcs)
    cx, cy = coeff_converter.sip2idc(img_wcs)
    # Convert the RA/Dec positions back to X/Y in output product image
    #_cpix_xyref = np.zeros((4,2),dtype=np.float64)

    # Start by setting up an array of points +/-0.5 pixels around CRVAL1,2
    # However, we must shift these positions by 1.0pix to match what
    # drizzle will use as its reference position for 'align=center'.
    _cpix = (img_wcs.wcs.crpix[0],img_wcs.wcs.crpix[1])
    _cpix_arr = np.array([_cpix,(_cpix[0],_cpix[1]+1.),
                       (_cpix[0]+1.,_cpix[1]+1.),(_cpix[0]+1.,_cpix[1])], dtype=np.float64)
    # Convert these positions to RA/Dec
    _cpix_rd = wmap.xy2rd(img_wcs,_cpix_arr[:,0],_cpix_arr[:,1])
    #for pix in xrange(len(_cpix_rd[0])):
    _cpix_xref,_cpix_yref = wmap.rd2xy(ref_wcs,_cpix_rd[0],_cpix_rd[1])
    _cpix_xyref = np.zeros((4,2),dtype=np.float64)
    _cpix_xyref[:,0] = _cpix_xref
    _cpix_xyref[:,1] = _cpix_yref
    
    """
    # needed to handle correctly subarrays and wfpc2 data
    if img_wcs.delta_refx == 0.0 and img_wcs.delta_refy == 0.0:
        offx, offy = (0.0,0.0)
    else:
        offx, offy = (1.0, 1.0)
    """
    offx, offy = (0.0,0.0)
    
    # Now, apply distortion model to input image XY positions
    #_cpix_xyc = np.zeros((4,2),dtype=np.float64)
    _cpix_xyc = utils.apply_idc(_cpix_arr, cx, cy, img_wcs.wcs.crpix, img_wcs.pscale, order=1)    

    # Need to get the XDELTA,YDELTA values included here in order to get this
    # to work with MDTng.
    #if in_refpix:
    #    _cpix_xyc += (in_refpix['XDELTA'], in_refpix['YDELTA'])

    # Perform a fit between:
    #       - undistorted, input positions: _cpix_xyc
    #       - X/Y positions in reference frame: _cpix_xyref
    abxt,cdyt = fitlin(_cpix_xyc,_cpix_xyref)

    # This correction affects the final fit when you are fitting
    # a WCS to itself (no distortion coeffs), so it needs to be
    # taken out in the coeffs file by modifying the zero-point value.
    #  WJH 17-Mar-2005
    abxt[2] -= ref_wcs.wcs.crpix[0] + offx 
    cdyt[2] -= ref_wcs.wcs.crpix[1] + offy

    return abxt,cdyt


def fitlin(imgarr,refarr):
    """ Compute the least-squares fit between two arrays.
        A Python translation of 'FITLIN' from 'drutil.f' (Drizzle V2.9).
    """
    # Initialize variables
    _mat = np.zeros((3,3),dtype=np.float64)
    _xorg = imgarr[0][0]
    _yorg = imgarr[0][1]
    _xoorg = refarr[0][0]
    _yoorg = refarr[0][1]
    _sigxox = 0.
    _sigxoy = 0.
    _sigxo = 0.
    _sigyox = 0.
    _sigyoy = 0.
    _sigyo = 0.

    _npos = len(imgarr)
    # Populate matrices
    for i in xrange(_npos):
        _mat[0][0] += np.power((imgarr[i][0] - _xorg),2)
        _mat[0][1] += (imgarr[i][0] - _xorg) * (imgarr[i][1] - _yorg)
        _mat[0][2] += (imgarr[i][0] - _xorg)
        _mat[1][1] += np.power((imgarr[i][1] - _yorg),2)
        _mat[1][2] += imgarr[i][1] - _yorg

        _sigxox += (refarr[i][0] - _xoorg)*(imgarr[i][0] - _xorg)
        _sigxoy += (refarr[i][0] - _xoorg)*(imgarr[i][1] - _yorg)
        _sigxo += refarr[i][0] - _xoorg
        _sigyox += (refarr[i][1] - _yoorg)*(imgarr[i][0] -_xorg)
        _sigyoy += (refarr[i][1] - _yoorg)*(imgarr[i][1] - _yorg)
        _sigyo += refarr[i][1] - _yoorg

    _mat[2][2] = _npos
    _mat[1][0] = _mat[0][1]
    _mat[2][0] = _mat[0][2]
    _mat[2][1] = _mat[1][2]

    # Now invert this matrix
    _mat = linalg.inv(_mat)

    _a  = _sigxox*_mat[0][0]+_sigxoy*_mat[0][1]+_sigxo*_mat[0][2]
    _b  = -1*(_sigxox*_mat[1][0]+_sigxoy*_mat[1][1]+_sigxo*_mat[1][2])
    #_x0 = _sigxox*_mat[2][0]+_sigxoy*_mat[2][1]+_sigxo*_mat[2][2]

    _c  = _sigyox*_mat[1][0]+_sigyoy*_mat[1][1]+_sigyo*_mat[1][2]
    _d  = _sigyox*_mat[0][0]+_sigyoy*_mat[0][1]+_sigyo*_mat[0][2]
    #_y0 = _sigyox*_mat[2][0]+_sigyoy*_mat[2][1]+_sigyo*_mat[2][2]

    _xt = _xoorg - _a*_xorg+_b*_yorg
    _yt = _yoorg - _d*_xorg-_c*_yorg

    return [_a,_b,_xt],[_c,_d,_yt]
