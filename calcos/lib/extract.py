from __future__ import division         # confidence high
import os
import numpy as np
from convolve import boxcar
import pyfits
import cosutil
import ccos
import dispersion
import getinfo
import xd_search
from calcosparam import *       # parameter definitions

def extract1D (input, incounts=None, output=None,
               update_input=True,
               location=None, extrsize=None, find_target=False):
    """Extract 1-D spectrum from 2-D image.

    @param input: name of either the flat-fielded count-rate image (in which
        case incounts must also be specified) or the corrtag table
    @type input: string
    @param incounts: name of the file containing the count-rate image,
        or None if input is the corrtag table
    @type incounts: string, or None
    @param output: name of the output file for 1-D extracted spectra
    @type output: string
    @param update_input: True if the input flt and counts files should be
        modified in-place by updating keywords regarding extraction location
    @type update_input: boolean
    @param location: the location (or list of three locations for NUV) of
        the spectrum in the cross-dispersion direction, in pixels; this
        is where the spectrum crosses the middle of the detector (index
        8192 for FUV, 512 for NUV).  None means the user did not specify
        the location.  If location was specified, that value will be used,
        regardless of the find_target switch.
    @type location: int or float, but could be a list or tuple for NUV, or None
    @param extrsize: the height of the extraction box (or list of three heights
        for NUV) in the cross-dispersion direction.  None means the user did
        not specify the extraction height.
    @type extrsize: integer, but could be a list or tuple for NUV, or None
    @param find_target: True means that we should search for the location of
        the target in the cross-dispersion direction; False means we should
        use the location determined from the wavecal or specified by the user.
        find_target will be locally set to False if location is not None.
    @type find_target: boolean
    """

    cosutil.printIntro ("Spectral Extraction")
    names = [("Input", input), ("Incounts", incounts), ("Output", output)]
    cosutil.printFilenames (names)
    cosutil.printMsg ("", VERBOSE)

    # Open the input files.
    ifd_e = pyfits.open (input, mode="readonly")
    if incounts is None:
        ifd_c = None
    else:
        ifd_c = pyfits.open (incounts, mode="readonly")

    phdr = ifd_e[0].header
    hdr = ifd_e[1].header
    info = getinfo.getGeneralInfo (phdr, hdr)
    switches = getinfo.getSwitchValues (phdr)
    reffiles = getinfo.getRefFileNames (phdr)
    is_wavecal = info["exptype"].find ("WAVE") >= 0
    if not is_wavecal and switches["wavecorr"] != "COMPLETE":
        cosutil.printWarning ("WAVECORR was not done for " + input)

    if is_wavecal:
       location = None
       extrsize = None
       find_target = False
    if location is None:
        if find_target:
            cosutil.printMsg ("Info:  Spectrum will be extracted where"
                              " one is found.", VERBOSE)
        else:
            cosutil.printMsg ("Info:  Spectrum will be extracted at location"
                              " based on XTRACTAB.", VERBOSE)
    else:
        cosutil.printMsg ("Info:  Spectrum will be extracted"
                          " at user-specified location.", VERBOSE)
    if extrsize is not None:
        cosutil.printMsg ("Info:  User-specified extraction height"
                          " will be used.", VERBOSE)

    # Check data types and lengths (if not scalar), and copy values for
    # location and extrsize to dictionary entries.  Override value of
    # find_target (set to False) if location was specified.
    (location, extrsize, find_target) = \
        checkLocation (info, location, extrsize, find_target)

    cosutil.printSwitch ("X1DCORR", switches)
    cosutil.printRef ("XTRACTAB", reffiles)
    cosutil.printRef ("DISPTAB", reffiles)
    cosutil.printSwitch ("HELCORR", switches)
    cosutil.printSwitch ("BACKCORR", switches)
    cosutil.printSwitch ("STATFLAG", switches)
    cosutil.printSwitch ("FLUXCORR", switches)
    if switches["fluxcorr"] == "PERFORM":
        cosutil.printRef ("fluxtab", reffiles)
        cosutil.printSwitch ("TDSCORR", switches)
        if switches["tdscorr"] == "PERFORM":
            cosutil.printRef ("tdstab", reffiles)

    # Create the output FITS header/data unit object.
    ofd = pyfits.HDUList (ifd_e[0])

    # Set the default length of the dispersion axis.
    if info["detector"] == "FUV":
        nelem = FUV_EXTENDED_X
    else:
        nelem = NUV_EXTENDED_X

    if info["npix"] == (0,):
        nrows = 0
    else:
        if info["detector"] == "FUV":
            nrows = FUV_SPECTRA
        else:
            nrows = NUV_SPECTRA
        if ifd_c is not None:
            # get the actual value of naxis (note:  dispaxis is one-indexed)
            dispaxis = max (info["dispaxis"], 1)
            key = "naxis" + str (dispaxis)
            nelem = hdr[key]
    rpt = str (nelem)                           # used for defining columns

    # Define output columns.
    col = []
    col.append (pyfits.Column (name="SEGMENT", format="4A"))
    col.append (pyfits.Column (name="EXPTIME", format="1D",
                disp="F8.3", unit="s"))
    col.append (pyfits.Column (name="NELEM", format="1J", disp="I6"))
    col.append (pyfits.Column (name="WAVELENGTH", format=rpt+"D",
                unit="angstrom"))
    col.append (pyfits.Column (name="FLUX", format=rpt+"E",
                unit="erg /s /cm**2 /angstrom"))
    col.append (pyfits.Column (name="ERROR", format=rpt+"E",
                unit="erg /s /cm**2 /angstrom"))
    col.append (pyfits.Column (name="GROSS", format=rpt+"E",
                unit="count /s"))
    col.append (pyfits.Column (name="GCOUNTS", format=rpt+"E",
                unit="count"))
    col.append (pyfits.Column (name="NET", format=rpt+"E",
                unit="count /s"))
    col.append (pyfits.Column (name="BACKGROUND", format=rpt+"E",
                unit="count /s"))
    col.append (pyfits.Column (name="DQ", format=rpt+"I"))
    col.append (pyfits.Column (name="DQ_WGT", format=rpt+"E"))
    cd = pyfits.ColDefs (col)

    hdu = pyfits.new_table (cd, header=hdr, nrows=nrows)
    hdu.name = "SCI"
    ofd.append (hdu)

    if nrows > 0:
        if info["detector"] == "FUV":
            segments = [info["segment"]]
        elif info["obstype"] == "IMAGING":
            segments = ["NUVA"]
        else:
            segments = ["NUVA", "NUVB", "NUVC"]
        # Extract the spectrum or spectra.
        doExtract (ifd_e, ifd_c, ofd, nelem,
                   segments, info, switches, reffiles, is_wavecal,
                   location, extrsize, find_target)
        if switches["fluxcorr"] == "PERFORM":
            # Convert net count rate to flux.
            doFluxCorr (ofd, info["opt_elem"], info["cenwave"],
                        info["aperture"], switches["tdscorr"], reffiles)
    # Update nrows, in case rows were skipped during 1-D extraction.
    nrows = ofd[1].data.shape[0]

    # Apply heliocentric Doppler correction to the wavelength array.
    if switches["helcorr"] == "PERFORM" or switches["helcorr"] == "COMPLETE":
        wavelength = ofd[1].data.field ("WAVELENGTH")
        for row in range (nrows):
            wl_row = wavelength[row]
            wl_row += (wl_row * (-hdr["v_helio"]) / SPEED_OF_LIGHT)
            wavelength[row][:] = wl_row
        phdr["helcorr"] = "COMPLETE"

    # Update the output header.
    ofd[1].header["bitpix"] = 8         # temporary, xxx
    ofd[0].header.update ("nextend", 1)
    cosutil.updateFilename (ofd[0].header, output)
    if ifd_c is None:                   # ifd_e is a corrtag table
        # Delete table-specific world coordinate system keywords.
        ofd[1].header = cosutil.delCorrtagWCS (ofd[1].header)
    else:                               # ifd_e is an flt image
        # Delete image-specific world coordinate system keywords.
        ofd[1].header = cosutil.imageHeaderToTable (ofd[1].header)
    updateArchiveSearch (ofd)           # update some keywords
    # Fix the aperture keyword, if it's RelMvReq.
    fixApertureKeyword (ofd, info["aperture"], info["detector"])
    if nrows > 0:
        ofd[0].header["x1dcorr"] = "COMPLETE"
        if switches["backcorr"] == "PERFORM":
            ofd[0].header["backcorr"] = "COMPLETE"
        # FLUXCORR and TDSCORR are updated in doFluxCorr.

    ofd.writeto (output, output_verify="silentfix")
    del ofd
    ifd_e.close()
    if ifd_c is not None:
        ifd_c.close()

    if update_input and nrows > 0:
        copyKeywordsToInput (output, input, incounts)

    if switches["statflag"] == "PERFORM":
        cosutil.doSpecStat (output)

def checkLocation (info, location, extrsize, find_target):
    """Check that location and height were specified correctly.

    @param info: keywords and values
    @type info: dictionary
    @param location: location(s) at which to extract spectrum or spectra
    @type location: integer, float, or sequence
    @param extrsize: extraction height (or heights for NUV)
    @type extrsize: integer or sequence
    @param find_target: 
    @type find_target: boolean

    @return: dictionary of locations (key is segment or stripe), dictionary of
        extraction heights (key is segment or stripe), and the find_target flag
        (set to False if location was not None).  The elements of the
        dictionaries may be None (i.e. if location is None or extrsize is None)
    @rtype: tuple of two dictionaries and a boolean flag
    """

    if location is None:
        if info["detector"] == "FUV":
            location = {info["segment"]: None}
        else:
            location = {"NUVA": None, "NUVB": None, "NUVC": None}
    else:
        find_target = False             # override
        if isinstance (location, int) or isinstance (location, float):
            if info["detector"] == "FUV":
                location = {info["segment"]: location}
            else:
                # This doesn't seem like a very useful case.
                location = {"NUVA": location, "NUVB": None, "NUVC": None}
        else:
            try:
                nelem = len (location)
            except TypeError:
                raise TypeError, "location must be an int, float, or sequence"
            if info["detector"] == "FUV":
                if nelem == 1:
                    location = {info["segment"]: location[0]}
                else:
                    raise TypeError, \
                    "for FUV, location may have only one element"
            elif info["detector"] == "NUV":
                if nelem > 3:
                    raise TypeError, \
                    "location may not have more than three elements"
                segments = ["NUVA", "NUVB", "NUVC"]
                temp = {"NUVA": None, "NUVB": None, "NUVC": None}
                for i in range (nelem):
                    temp[segments[i]] = location[i]
                location = temp

    if extrsize is None:
        if info["detector"] == "FUV":
            extrsize = {info["segment"]: None}
        else:
            extrsize = {"NUVA": None, "NUVB": None, "NUVC": None}
    else:
        if isinstance (extrsize, int):
            if info["detector"] == "FUV":
                extrsize = {info["segment"]: extrsize}
            else:
                extrsize = {"NUVA": extrsize,
                            "NUVB": extrsize,
                            "NUVC": extrsize}
        else:
            try:
                nelem = len (extrsize)
            except TypeError:
                raise TypeError, "extrsize must be an integer or sequence"
            if info["detector"] == "FUV":
                if nelem == 1:
                    extrsize = {info["segment"]: extrsize[0]}
                else:
                    raise TypeError, \
                    "for FUV, extrsize may have only one element"
            elif info["detector"] == "NUV":
                if nelem == 1:
                    extrsize = {"NUVA": extrsize[0],
                                "NUVB": extrsize[0],
                                "NUVC": extrsize[0]}
                else:
                    if nelem > 3:
                        raise TypeError, \
                        "extrsize may not have more than three elements"
                    segments = ["NUVA", "NUVB", "NUVC"]
                    temp = {"NUVA": None, "NUVB": None, "NUVC": None}
                    for i in range (nelem):
                        temp[segments[i]] = extrsize[i]
                    extrsize = temp

    return (location, extrsize, find_target)

def doExtract (ifd_e, ifd_c, ofd, nelem,
               segments, info, switches, reffiles, is_wavecal,
               location, extrsize, find_target=False):
    """Extract either FUV or NUV data.

    This calls a routine to do the extraction for one segment, and it
    assigns the results to one row of the output table.

    @param ifd_e: HDUList for either the effective count-rate image or for
        the corrtag events table
    @type ifd_e: PyFITS HDUList object
    @param ifd_c: HDUList for the count-rate image, or None if the input is
        a corrtag events table
    @type ifd_c: PyFITS HDUList object, or None
    @param ofd: HDUList for the output table, modified in-place
    @type ofd: PyFITS HDUList object
    @param nelem: number of elements in current segment of output data
    @type nelem: int
    @param segments: the segment names, one for FUV, three for NUV
    @type segments: list
    @param info: keywords and values
    @type info: dictionary
    @param switches: calibration switch values
    @type switches: dictionary
    @param reffiles: reference file names
    @type reffiles: dictionary
    @param is_wavecal: true if the observation is a wavecal, based on exptype
    @type is_wavecal: boolean
    @param location: locations of the spectrum in the cross-dispersion
        direction, in pixels; this is where the spectrum crosses the middle of
        the detector (index 8192 for FUV, 512 for NUV).  A key value may be
        None, which means the user did not specify the location.
    @type location: dictionary with segment or stripe as key
    @param extrsize: the height of the extraction box (or list of three heights
        for NUV) in the cross-dispersion direction.  A key value may be None,
        which means the user did not specify the extraction height.
    @type extrsize: dictionary with segment or stripe as key
    @param find_target: True means that we should search for the location of
        the target in the cross-dispersion direction; False means we should
        use the location determined from the wavecal or specified by the user.
    @type find_target: boolean
    """

    hdr = ifd_e[1].header
    outdata = ofd[1].data

    is_corrtag = (ifd_c is None)
    if is_corrtag:              # the input is a corrtag table
        (xi, eta, dq, epsilon) = getColumns (ifd_e, info["detector"])
        if info["detector"] == "FUV":
            axis_height = FUV_Y
            axis_length = FUV_EXTENDED_X
            segment = segments[0]
        else:
            axis_height = NUV_Y
            axis_length = NUV_EXTENDED_X
            segment = "NUVB"
        # populate the DQ array
        # xxx temporary, should be improved
        shift1 = hdr.get ("SHIFT1" + segment[-1], 0.)
        shift2 = hdr.get ("SHIFT2" + segment[-1], 0.)
        minmax_shift_dict = {}
        minmax_shift_dict[(0, 1024)] = [shift1, shift1, shift2, shift2] # xxx
        minmax_doppler = (0., 0.)       # xxx replace with actual values
        doppler_boundary = 512          # xxx replace with actual value
        dq_array = np.zeros ((axis_height,axis_length), dtype=np.int16)
        cosutil.updateDQArray (reffiles["bpixtab"], info, dq_array,
                               minmax_shift_dict,
                               minmax_doppler, doppler_boundary)

    row = 0
    for segment in segments:

        filter = {"segment": segment,
                  "opt_elem": info["opt_elem"],
                  "cenwave": info["cenwave"],
                  "aperture": info["aperture"]}
        xtract_info = cosutil.getTable (reffiles["xtractab"], filter)
        # Include fpoffset in the filter for disptab.
        filter["fpoffset"] = info["fpoffset"]
        disp_rel = dispersion.Dispersion (reffiles["disptab"], filter, True)
        if xtract_info is None or not disp_rel.isValid():
            continue
        slope = xtract_info.field ("slope")[0]

        if is_wavecal:
            dpixel1 = 0.
            key = "shift2" + segment[-1]
            shift2 = hdr.get (key, 0.)
        else:
            key = "dpixel1" + segment[-1]
            dpixel1 = hdr.get (key, 0.)
            shift2 = 0.

        # xdisp_locn will be the user-specified location in cross-dispersion
        # direction (or None, if the user did not specify a value).
        # xd_locn (assigned later) will be either xdisp_locn (if specified),
        # or the value found by searching (if find_target is True), or the
        # default value plus shift2.
        if location is None:
            xdisp_locn = None
        else:
            xdisp_locn = location[segment]
        if extrsize is None:
            xdisp_size = None
        else:
            xdisp_size = extrsize[segment]

        outdata.field ("NELEM")[row] = nelem

        # These are pixel coordinates.
        pixel = np.arange (nelem, dtype=np.float64)

        x_offset = hdr.get ("x_offset", 0)

        # Correct for the extra pixels (if any) in the dispersion direction.
        pixel -= x_offset

        pixel += dpixel1                # dpixel1 will be 0 for a wavecal
        wavelength = disp_rel.evalDisp (pixel)
        disp_rel.close()

        # S/N of the flat field
        snr_ff = getSnrFf (switches, reffiles, segment)

        dispaxis = max (info["dispaxis"], 1)
        axis = 2 - dispaxis             # 1 --> 1,  2 --> 0

        # For FUV, the keyword for exposure time depends on segment.
        exptime_key = cosutil.exptimeKeyword (segment)
        exptime = hdr.get (exptime_key, default=hdr["exptime"])

        if is_corrtag:
            key = "shift1" + segment[-1]
            shift1 = ofd[1].header.get (key, 0.)
            (N_i, ERR_i, GC_i, GCOUNTS_i, BK_i, DQ_i, DQ_WGT_i) = \
                extractCorrtag (xi, eta, dq, epsilon, dq_array,
                                ofd[1].header, segment, axis_length,
                                x_offset, hdr["sdqflags"], snr_ff,
                                exptime, switches["backcorr"], axis,
                                xtract_info, shift1, shift2,
                                xdisp_locn, xdisp_size, find_target)
        else:
            (N_i, ERR_i, GC_i, GCOUNTS_i, BK_i, DQ_i, DQ_WGT_i) = \
             extractSegment (ifd_e["SCI"].data, ifd_c["SCI"].data,
                             ifd_e["DQ"].data, ofd[1].header, segment,
                             x_offset, hdr["sdqflags"], snr_ff,
                             exptime, switches["backcorr"], axis,
                             xtract_info, shift2,
                             info, wavelength, is_wavecal,
                             xdisp_locn, xdisp_size, find_target)
        del xtract_info

        outdata.field ("SEGMENT")[row] = segment
        outdata.field ("EXPTIME")[row] = exptime
        outdata.field ("WAVELENGTH")[row][:] = wavelength
        outdata.field ("FLUX")[row][:] = 0.
        outdata.field ("ERROR")[row][:] = ERR_i
        outdata.field ("GROSS")[row][:] = GC_i
        outdata.field ("GCOUNTS")[row][:] = GCOUNTS_i
        outdata.field ("NET")[row][:] = N_i
        outdata.field ("BACKGROUND")[row][:] = BK_i
        outdata.field ("DQ")[row][:] = DQ_i
        outdata.field ("DQ_WGT")[row][:] = DQ_WGT_i

        row += 1

    # Remove unused rows, if any.
    if row < len (outdata):
        data = outdata[0:row]
        ofd[1].data = data.copy()
        del data

def postargOffset (phdr, dispaxis):
    """Get the offset to shift2 if postarg is non-zero.

    I don't think this should be used, but I'll leave the function here
    for the time being.  If it were to be used, the function value would
    be added to (or subtracted from?) shift2 in doExtract, e.g.:
        shift2 = 0.              # cross-dispersion direction
        shift2 += postargOffset (ifd_e[0].header, hdr["dispaxis"])

    @param phdr: primary header
    @type phdr: pyfits Header object
    @param dispaxis: dispersion axis (1 or 2)
    @type dispaxis: int
    @return: offset in pixels to be added to cross-dispersion location
    @rtype: float

    xxx The plate scale should be gotten from a header keyword.
    xxx The sign of the offset needs to be checked.
    """

    # pixels per arcsecond in the cross-dispersion direction
    plate_scale = {
        "G130M":  9.02,
        "G160M": 10.12,
        "G140L":  9.48,
        "G185M": 41.85,
        "G225M": 41.89,
        "G285M": 41.80,
        "G230L": 42.27}

    if dispaxis == 1:
        postarg_xdisp = phdr.get ("postarg2", 0.)
    elif dispaxis == 2:
        postarg_xdisp = phdr.get ("postarg1", 0.)
    else:
        return 0.

    opt_elem = phdr["opt_elem"]

    return postarg_xdisp * plate_scale[opt_elem]

def getColumns (ifd_e, detector):
    """Get the appropriate columns from the events table extension.

    @param ifd_e: HDUList for the corrtag events table
    @type ifd_e: PyFITS HDUList object
    @param detector: detector name ("FUV" or "NUV")
    @type detector: string

    @return: columns from the corrtag table
    @rtype: tuple of arrays

    The returned columns xi, eta, dq and epsilon are as follows:
        xi is the array of positions in the dispersion direction
        eta is the array of positions in the cross-dispersion direction
        dq is the array of data quality flags
        epsilon is the array of weights (inverse flat field and deadtime
          correction)
    There is one element for each detected photon.
    """

    data = ifd_e[1].data

    if cosutil.findColumn (data, "xfull"):
        xi = data.field ("xfull")
    else:
        xi = data.field ("xdopp")
    if cosutil.findColumn (data, "yfull"):
        eta = data.field ("yfull")
    else:
        if detector == "FUV":
            eta = data.field ("ycorr")
        else:
            eta = data.field ("rawy")

    dq = data.field ("dq")
    epsilon = data.field ("epsilon")

    return (xi, eta, dq, epsilon)

def getSnrFf (switches, reffiles, segment):
    """Get the signal-to-noise ratio of the flat field data.

    @param switches: calibration switch values
    @type switches: dictionary
    @param reffiles: reference file names
    @type reffiles: dictionary
    @param segment: segment (or stripe) name
    @type segment: string

    @return: signal-to-noise ratio of the flat field
    @rtype: float

    If the flat-field correction has been done, this function reads the
    keyword SNR_FF from the appropriate header of the flat field image
    and returns that value; otherwise, this function returns zero.
    """

    if switches["flatcorr"] == "COMPLETE":
        fd_flat = pyfits.open (reffiles["flatfile"], mode="readonly")
        if segment in ["FUVA", "FUVB"]:
            flat_hdr = fd_flat[segment].header
        else:
            flat_hdr = fd_flat[1].header
        snr_ff = flat_hdr.get ("snr_ff", 0.)
        fd_flat.close()
        del fd_flat
    else:
        snr_ff = 0.

    return snr_ff

def extractSegment (e_data, c_data, e_dq_data, ofd_header, segment,
                    x_offset, sdqflags, snr_ff,
                    exptime, backcorr, axis,
                    xtract_info, shift2,
                    info, wavelength, is_wavecal,
                    xdisp_locn=None, xdisp_size=None, find_target=False):

    """Extract a 1-D spectrum for one segment or stripe.

    This does the actual extraction, returning the results as a tuple.

    @param e_data: SCI data from the flt file ('e' for effective count rate)
    @type e_data: 2-D numpy array
    @param c_data: SCI data from the counts file (count rate)
    @type c_data: 2-D numpy array
    @param e_dq_data: DQ data from the flt file
    @type e_dq_data: 2-D numpy array
    @param ofd_header: header of the output table (for updating keywords)
    @type ofd_header: pyfits Header object
    @param segment: FUVA or FUVB, etc. (only used for updating keywords)
    @type segment: string
    @param x_offset: offset of the detector in the output array
    @type x_offset: int
    @param sdqflags: "serious" data quality flags
    @type sdqflags: int
    @param snr_ff: the signal-to-noise ratio of the flat field reference file
        (from the extension header of the flat field)
    @type snr_ff: float
    @param exptime: exposure time (seconds), from the header keyword
    @type exptime: float
    @param backcorr: "PERFORM" if background subtraction is to be done
    @type backcorr: int
    @param axis: the dispersion axis, 0 (Y) or 1 (X)
    @type axis: int
    @param xtract_info: one row of the xtractab
    @type xtract_info: PyFITS record object
    @param shift2: offset in the cross-dispersion direction
    @type shift2: float
    @param info: keywords and values
    @type info: dictionary
    @param wavelength: wavelength at each pixel (needed if find_target is True)
    @type wavelength: array
    @param is_wavecal: true if the observation is a wavecal, based on exptype
    @type is_wavecal: boolean
    @param xdisp_locn: user-specified location in cross-dispersion direction
    @type xdisp_locn: int or float, or None if not specified
    @param xdisp_size: user-specified height of extraction box
    @type xdisp_size: int, or None if not specified
    @param find_target: search for the cross-disp location of the target?
    @type find_target: boolean

    @return: net count rate, error estimate, gross count rate, gross counts,
        background count rate, data quality array, data quality weight array
    @rtype: tuple of seven 1-D arrays

    An "_ij" suffix indicates a 2-D array; here they will all be sections
    extracted from full images.  An "_i" suffix indicates a 1-D array
    which is the result of summing the 2-D array with the same prefix in
    the cross-dispersion direction.  Variables beginning with a capital
    letter are included in the returned tuple.

      e_i       effective count rate, extracted from ifd_e[1].data
      GC_i      gross count rate, extracted from ifd_c[1].data
      GCOUNTS_i gross counts, extracted from ifd_c[1].data
      BK_i      background count rate
      N_i       net count rate
      eps_i     effective count rate / gross count rate
      ERR_i     error estimate for net count rate
      DQ_i      data quality flags, bitwise OR of input DQ array
      DQ_WGT_i  data quality weight array
    """

    slope           = xtract_info.field ("slope")[0]
    b_spec          = xtract_info.field ("b_spec")[0]   # may be changed below
    extr_height     = xtract_info.field ("height")[0]   # but see xdisp_size
    b_bkg1          = xtract_info.field ("b_bkg1")[0]
    b_bkg2          = xtract_info.field ("b_bkg2")[0]
    if cosutil.findColumn (xtract_info, "b_hgt1"):
        bkg_height1  = xtract_info.field ("b_hgt1")[0]
        bkg_height2  = xtract_info.field ("b_hgt2")[0]
    else:
        bkg_height1  = xtract_info.field ("bheight")[0]
        bkg_height2  = bkg_height1
    bkg_smooth      = xtract_info.field ("bwidth")[0]

    axis_length = e_data.shape[axis]

    offset_to_middle = slope * (axis_length // 2 - x_offset)
    # nominal location of spectrum, where it crosses the middle of the
    # flt or counts image
    xd_nominal = b_spec + shift2 + offset_to_middle

    if is_wavecal:
        xd_offset = -999.
    else:
        # Search for the target spectrum.
        (offset2, found_locn, found_locn_sigma) = \
                xd_search.xdSearch (e_data,
                                    e_dq_data, wavelength,
                                    axis, slope, b_spec,
                                    x_offset, info["detector"])
        if found_locn is None:
            xd_offset = 0.
            find_target = False         # turn off for this segment/stripe
            message = "%s spectrum was not found; nominal y = %.2f" % \
                        (segment, xd_nominal)
        else:
            # offset from found location to nominal location
            xd_offset = offset2
            message = "%s spectrum was found at y = %.2f" \
                      " vs. nominal y = %.2f" % \
                                (segment,
                                 found_locn + offset_to_middle,
                                 xd_nominal)
        cosutil.printMsg (message, VERBOSE)

    # b_spec is where the spectrum crosses the left edge of the array.
    # xd_locn will be set to either the user-specified value (if it was
    # specified) or the location based on the wavecal.  In either case,
    # xd_locn is where the spectrum crosses the middle of the array.
    if xdisp_locn is None:
        if find_target:         # use the location we found above
            b_spec = found_locn
            xd_locn = found_locn + offset_to_middle
        else:
            # add the shift to the nominal location; assign a value to xd_locn
            # (which will be used to update a header keyword)
            b_spec += shift2
            xd_locn = b_spec + slope * (axis_length // 2 - x_offset)
            b_bkg1 += shift2
            b_bkg2 += shift2
    else:
        # use the user-specified value, but convert to b_spec, the Y location
        # of the spectrum at X = x_offset
        b_spec = xdisp_locn - slope * (axis_length // 2 - x_offset)
        xd_locn = xdisp_locn
    cosutil.printMsg ("Spectrum will be extracted at y = %.2f" % xd_locn,
                      VERBOSE)

    if xdisp_size is not None:
        extr_height = xdisp_size        # use the user-specified value

    # Compute the data quality and data quality weight arrays.
    DQ_i = np.zeros (axis_length, dtype=np.int16)
    if e_dq_data is not None:

        # Get data quality flags within extraction region.
        dq_ij = np.zeros ((extr_height, axis_length), dtype=np.int16)
        ccos.extractband (e_dq_data, axis, slope, b_spec, x_offset, dq_ij)
        # For each i, DQ_i[i] will be the bitwise OR of dq_ij[:,i].
        ccos.dq_or (dq_ij, DQ_i)

        # In bad_ij and bad_i, 0 means OK and 1 means bad
        bad_ij = np.zeros ((extr_height, axis_length), dtype=np.int32)
        bad_ij[:,:] = np.where (np.bitwise_and (dq_ij, sdqflags), 1, 0)
        bad_i = bad_ij.sum (axis=0)
        # Any bad pixel in extraction region?  DQ_WGT is a weight,
        # so 0 is bad and 1 is good.
        DQ_WGT_i = np.where (bad_i > 0, 0., 1.)
        del dq_ij, bad_ij, bad_i
    else:
        DQ_WGT_i = np.ones (axis_length, dtype=np.float32)

    e_ij = np.zeros ((extr_height, axis_length), dtype=np.float32)
    ccos.extractband (e_data, axis, slope, b_spec, x_offset, e_ij)

    GC_ij = np.zeros ((extr_height, axis_length), dtype=np.float32)
    ccos.extractband (c_data, axis, slope, b_spec, x_offset, GC_ij)

    e_i  = e_ij.sum (axis=0)
    GC_i = GC_ij.sum (axis=0)
    GCOUNTS_i = GC_i * exptime          # gross counts (not count rate)

    eps_i = e_i / np.where (GC_i <= 0., 1., GC_i)
    # default value when there are no counts
    eps_i = np.where (e_i == 0., 1., eps_i)
    del e_ij, e_i

    bkg_norm = float (extr_height) / (float (bkg_height1 + bkg_height2))
    if backcorr == "PERFORM":
        BK1_ij = np.zeros ((bkg_height1, axis_length), dtype=np.float32)
        dq1_ij = np.zeros ((bkg_height1, axis_length), dtype=np.int16)
        BK2_ij = np.zeros ((bkg_height2, axis_length), dtype=np.float32)
        dq2_ij = np.zeros ((bkg_height2, axis_length), dtype=np.int16)
        # Get the background data from the counts image.
        ccos.extractband (c_data, axis, slope, b_bkg1, x_offset, BK1_ij)
        ccos.extractband (c_data, axis, slope, b_bkg2, x_offset, BK2_ij)
        # Get the data quality array from the flt file.
        ccos.extractband (e_dq_data, axis, slope, b_bkg1, x_offset, dq1_ij)
        ccos.extractband (e_dq_data, axis, slope, b_bkg2, x_offset, dq2_ij)
        good1_ij = dq1_ij.copy()
        good2_ij = dq2_ij.copy()
        # In good[12]_ij, 1 means OK and 0 means bad.
        good1_ij[:,:] = np.where (np.bitwise_and (dq1_ij, sdqflags), 0, 1)
        good2_ij[:,:] = np.where (np.bitwise_and (dq2_ij, sdqflags), 0, 1)
        # Use the good[12]_ij arrays as a mask to exclude bad data in the
        # background regions.
        BK1_ij *= good1_ij
        BK2_ij *= good2_ij
        BK_i = BK1_ij.sum (axis=0) + BK2_ij.sum (axis=0)

        # The sum along axis=0 gives the number of good pixels in each column.
        # Use this sum to correct (rescale) the background to account for
        # pixels that are flagged as bad.
        good_i = good1_ij.sum (axis=0, dtype=np.float32) + \
                 good2_ij.sum (axis=0, dtype=np.float32)
        # If good_i is zero, the background will also be zero, so it doesn't
        # matter what we set good_i to as long as it's not zero (we're going
        # to divide by it).
        good_i = np.where (good_i > 0., good_i, 1.)
        # Correct for regions excluded because they're flagged as bad.
        BK_i *= (float (bkg_height1 + bkg_height2)) / good_i
        # Scale the background to the spectral extraction height.
        BK_i *= bkg_norm
        if x_offset > 0:
            # assumes x_offset only for NUV
            key = "shift1" + segment[-1].lower()
            i = x_offset - ofd_header.get (key, 0.)
            i = int (round (i))
            j = i + NUV_X
            i = max (i, 0)
            j = min (j, axis_length-1)
            temp_bk = BK_i[i:j].copy()
            boxcar (temp_bk, (bkg_smooth,), output=temp_bk, mode='nearest')
            BK_i[i:j] = temp_bk.copy()
            del temp_bk
        else:
            boxcar (BK_i, (bkg_smooth,), output=BK_i, mode='nearest')
    else:
        BK_i = np.zeros (axis_length, dtype=np.float32)

    N_i = eps_i * (GC_i - BK_i)

    if snr_ff > 0.:
        term1_i = (N_i * exptime / (extr_height * snr_ff))**2
    else:
        term1_i = 0.
    term2_i = eps_i**2 * exptime * \
                (GC_i + BK_i * (bkg_norm / float (bkg_smooth)))
    if exptime > 0.:
        ERR_i = np.sqrt (term1_i + term2_i) / exptime
    else:
        ERR_i = N_i * 0.

    updateExtractionKeywords (ofd_header, segment,
                              slope, extr_height,
                              xd_nominal, xd_locn, xd_offset,
                              b_bkg1, b_bkg2, bkg_height1, bkg_height2)

    return (N_i, ERR_i, GC_i, GCOUNTS_i, BK_i, DQ_i, DQ_WGT_i)

def extractCorrtag (xi, eta, dq, epsilon, dq_array,
                    ofd_header, segment, axis_length,
                    x_offset, sdqflags, snr_ff,
                    exptime, backcorr, axis,
                    xtract_info, shift1, shift2,
                    xdisp_locn=None, xdisp_size=None, find_target=False):
    """Extract a 1-D spectrum for one segment or stripe.

    @param xi: column of pixel coordinates in the dispersion direction
    @type xi: 1-D numpy array
    @param eta: column of pixel coordinates in the cross-dispersion direction
    @type eta: 1-D numpy array
    @param dq: column of data quality flags
    @type dq: 1-D numpy array
    @param epsilon: column of weights for flat field or nonlinearity
    @type epsilon: 1-D numpy array
    @param dq_array: DQ array, created from the bad pixel table
    @type dq_array: 2-D numpy array
    @param ofd_header: header of the output table (for updating keywords)
    @type ofd_header: pyfits Header object, or None
    @param segment: FUVA or FUVB, etc. (only used for updating keywords)
    @type segment: string
    @param axis_length: length of dispersion axis
    @type axis_length: int
    @param x_offset: offset of the detector in the output array
    @type x_offset: int
    @param sdqflags: "serious" data quality flags
    @type sdqflags: int
    @param snr_ff: the signal-to-noise ratio of the flat field reference file
    @type snr_ff: float
    @param exptime: exposure time (seconds)
    @type exptime: float
    @param backcorr: "PERFORM" if background subtraction is to be done
    @type backcorr: int
    @param axis: the dispersion axis, 0 (Y) or 1 (X)
    @type axis: int
    @param xtract_info: one row of the xtractab
    @type xtract_info: PyFITS record object
    @param shift1: offset in the dispersion direction (used for NUV in the
        section for smoothing the background)
    @type shift1: float
    @param shift2: offset in the cross-dispersion direction
    @type shift2: float
    @param xdisp_locn: user-specified location in cross-dispersion direction
    @type xdisp_locn: int or float, or None if not specified
    @param xdisp_size: user-specified height of extraction box
    @type xdisp_size: int or float, or None if not specified
    @param find_target: search for the cross-disp location of the target?
    @type find_target: boolean

    @return: net count rate, error estimate, gross count rate, gross counts,
        background count rate, data quality array, data quality weight array
    @rtype: tuple of seven 1-D arrays
    """

    slope           = xtract_info.field ("slope")[0]
    b_spec          = xtract_info.field ("b_spec")[0]   # but see xdisp_locn
    extr_height     = xtract_info.field ("height")[0]   # but see xdisp_size
    b_bkg1          = xtract_info.field ("b_bkg1")[0]
    b_bkg2          = xtract_info.field ("b_bkg2")[0]
    if cosutil.findColumn (xtract_info, "b_hgt1"):
        bkg_height1  = xtract_info.field ("b_hgt1")[0]
        bkg_height2  = xtract_info.field ("b_hgt2")[0]
    else:
        bkg_height1  = xtract_info.field ("bheight")[0]
        bkg_height2  = bkg_height1
    bkg_smooth      = xtract_info.field ("bwidth")[0]

    offset_to_middle = slope * (axis_length // 2 - x_offset)
    # nominal location of spectrum, where it crosses the middle of the
    # flt or counts image
    xd_nominal = b_spec + shift2 + offset_to_middle

    # xd_locn is either the user-specified value (if it was specified) or the
    # location based on the wavecal; in either case, it's where the spectrum
    # crosses the middle of the array, not the left edge of the array.
    if xdisp_locn is None:
        if find_target:
            b_spec += shift2
            xd_locn = b_spec + slope * (axis_length // 2 - x_offset)
            # xxx not implemented yet xxx
            #y_nominal = b_spec + shift2
            # xxx need different arguments for xdSearch for corrtag xxx
            #(shift2, b_spec, b_spec_sigma) = xd_search.xdSearch (e_data,
            #                    e_dq_data, wavelength,
            #                    axis, slope, b_spec,
            #                    x_offset, info["detector"], info["opt_elem"])
            # xxx check whether b_spec is None
            #message = "Spectrum found at y = %.2f (nominal y = %.2f)." % \
            #           (xd_locn, y_nominal + offset_to_middle)
            #cosutil.printMsg (message, VERBOSE)
        else:
            # add the shift to the nominal location; assign a value to xd_locn
            # (which will be used to update a header keyword)
            b_spec += shift2
            xd_locn = b_spec + slope * (axis_length // 2 - x_offset)
            b_bkg1 += shift2
            b_bkg2 += shift2
    else:
        # use the user-specified value, but convert to b_spec, the intersection
        # with the left edge of the array
        b_spec = xdisp_locn - slope * (axis_length // 2 - x_offset)
        xd_locn = xdisp_locn

    if xdisp_size is not None:
        extr_height = xdisp_size        # use the user-specified value

    # Compute the data quality and data quality weight arrays.
    DQ_i = np.zeros (axis_length, dtype=np.int16)
    if dq_array is not None:

        # Get data quality flags within extraction region.
        dq_ij = np.zeros ((extr_height, axis_length), dtype=np.int16)
        ccos.extractband (dq_array, axis, slope, b_spec, x_offset, dq_ij)
        # For each i, DQ_i[i] will be the bitwise OR of dq_ij[:,i].
        ccos.dq_or (dq_ij, DQ_i)

        # In bad_ij and bad_i, 0 means OK and 1 means bad
        bad_ij = np.zeros ((extr_height, axis_length), dtype=np.int32)
        bad_ij[:,:] = np.where (np.bitwise_and (dq_ij, sdqflags), 1, 0)
        bad_i = bad_ij.sum (axis=0)
        # Any bad pixel in extraction region?  DQ_WGT is a weight,
        # so 0 is bad and 1 is good.
        DQ_WGT_i = np.where (bad_i > 0, 0., 1.)
        del dq_ij, bad_ij, bad_i
    else:
        DQ_WGT_i = np.ones (axis_length, dtype=np.float64)

    e_ij = np.zeros ((extr_height, axis_length), dtype=np.float64)
    ccos.xy_extract (xi, eta, e_ij, slope, b_spec,
                     x_offset, dq, SERIOUS_DQ_FLAGS, epsilon)

    GC_ij = np.zeros ((extr_height, axis_length), dtype=np.float64)
    ccos.xy_extract (xi, eta, GC_ij, slope, b_spec,
                     x_offset, dq, SERIOUS_DQ_FLAGS)

    e_ij /= exptime
    e_i = e_ij.sum (axis=0)
    GCOUNTS_i = GC_ij.sum (axis=0)      # gross counts (not count rate)
    GC_i = GCOUNTS_i / exptime          # gross count rate
    del GC_ij

    eps_i = e_i / np.where (GC_i <= 0., 1., GC_i)
    # default value when there are no counts
    eps_i = np.where (e_i == 0., 1., eps_i)
    del e_ij, e_i

    bkg_norm = float (extr_height) / (float (bkg_height1 + bkg_height2))
    if backcorr == "PERFORM":
        BK1_ij = np.zeros ((bkg_height1, axis_length), dtype=np.float64)
        dq1_ij = np.zeros ((bkg_height1, axis_length), dtype=np.int16)
        BK2_ij = np.zeros ((bkg_height2, axis_length), dtype=np.float64)
        dq2_ij = np.zeros ((bkg_height2, axis_length), dtype=np.int16)
        # Get the background data.
        ccos.xy_extract (xi, eta, BK1_ij, slope, b_bkg1, x_offset)
        ccos.xy_extract (xi, eta, BK2_ij, slope, b_bkg2, x_offset)
        # Get the data quality array from the flt file.
        ccos.extractband (dq_array, axis, slope, b_bkg1, x_offset, dq1_ij)
        ccos.extractband (dq_array, axis, slope, b_bkg2, x_offset, dq2_ij)
        good1_ij = dq1_ij.copy()
        good2_ij = dq2_ij.copy()
        # In good[12]_ij, 1 means OK and 0 means bad.
        good1_ij[:,:] = np.where (np.bitwise_and (dq1_ij, sdqflags), 0, 1)
        good2_ij[:,:] = np.where (np.bitwise_and (dq2_ij, sdqflags), 0, 1)
        # Use the good[12]_ij arrays as a mask to exclude bad data in the
        # background regions.
        BK1_ij *= good1_ij
        BK2_ij *= good2_ij
        BK_i = BK1_ij.sum (axis=0) + BK2_ij.sum (axis=0)
        BK_i /= exptime

        # The sum along axis=0 gives the number of good pixels in each column.
        # Use this sum to correct (rescale) the background to account for
        # pixels that are flagged as bad.
        good_i = good1_ij.sum (axis=0, dtype=np.float64) + \
                 good2_ij.sum (axis=0, dtype=np.float64)
        # If good_i is zero, the background will also be zero, so it doesn't
        # matter what we set good_i to as long as it's not zero (we're going
        # to divide by it).
        good_i = np.where (good_i > 0., good_i, 1.)
        # Correct for regions excluded because they're flagged as bad.
        BK_i *= (float (bkg_height1 + bkg_height2)) / good_i
        # Scale the background to the spectral extraction height.
        BK_i *= bkg_norm
        if x_offset > 0:
            i = x_offset - shift1
            i = int (round (i))
            j = i + NUV_X       # assumes x_offset only for NUV
            i = max (i, 0)
            j = min (j, axis_length-1)
            temp_bk = BK_i[i:j].copy()
            boxcar (temp_bk, (bkg_smooth,), output=temp_bk, mode='nearest')
            BK_i[i:j] = temp_bk.copy()
            del temp_bk
        else:
            boxcar (BK_i, (bkg_smooth,), output=BK_i, mode='nearest')
    else:
        BK_i = np.zeros (axis_length, dtype=np.float64)

    N_i = eps_i * (GC_i - BK_i)

    if snr_ff > 0.:
        term1_i = (N_i * exptime / (extr_height * snr_ff))**2
    else:
        term1_i = 0.
    term2_i = eps_i**2 * exptime * \
                (GC_i + BK_i * (bkg_norm / float (bkg_smooth)))
    if exptime > 0.:
        sum_terms = term1_i + term2_i
        sum_terms = np.where (sum_terms > 0, sum_terms, 0.)
        ERR_i = np.sqrt (sum_terms) / exptime
    else:
        ERR_i = N_i * 0.
    if ofd_header is not None:
        xd_offset = -999.               # not implemented yet
        updateExtractionKeywords (ofd_header, segment,
                                  slope, extr_height,
                                  xd_nominal, xd_locn, xd_offset,
                                  b_bkg1, b_bkg2, bkg_height1, bkg_height2)

    return (N_i, ERR_i, GC_i, GCOUNTS_i, BK_i, DQ_i, DQ_WGT_i)

def doFluxCorr (ofd, opt_elem, cenwave, aperture, tdscorr, reffiles):
    """Convert net counts to flux, updating flux and error columns.

    The correction to flux is made by dividing by the appropriate row
    in the fluxtab.  If a time-dependent sensitivity table (tdstab) has
    been specified, the flux and error will be corrected to the time of
    observation.

    @param ofd: HDUList for the output table; the primary header will be
        modified to set FLUXCORR to COMPLETE, and TDSCORR may be set to
        either COMPLETE or SKIPPED
    @type ofd: PyFITS HDUList object
    @param opt_elem: grating name
    @type opt_elem: string
    @param cenwave: central wavelength
    @type cenwave: integer
    @param aperture: PSA, BOA, WCA
    @type aperture: string
    @param tdscorr: calibration switch, time-dependent sensitivity correction
    @type tdscorr: string
    @param reffiles: dictionary of reference file names
    @type reffiles: dictionary
    """

    outdata = ofd[1].data
    nrows = outdata.shape[0]
    segment = outdata.field ("SEGMENT")
    wavelength = outdata.field ("WAVELENGTH")
    net = outdata.field ("NET")
    flux = outdata.field ("FLUX")
    error = outdata.field ("ERROR")

    # segment will be added to filter in the loop
    filter = {"opt_elem": opt_elem,
              "cenwave": cenwave,
              "aperture": aperture}

    fluxtab = reffiles["fluxtab"]

    for row in range (nrows):
        pharange = cosutil.getPulseHeightRange (ofd[1].header, segment[row])
        # xxx this is temporary; eventually select the row based on pharange
        ref_pharange = cosutil.tempPulseHeightRange (fluxtab)
        cosutil.comparePulseHeightRanges (pharange, ref_pharange, fluxtab)
        factor = np.zeros (len (flux[row]), dtype=np.float32)
        filter["segment"] = segment[row]
        flux_info = cosutil.getTable (fluxtab, filter, exactly_one=True)
        # Interpolate sensitivity at each wavelength.
        wl_phot = flux_info.field ("wavelength")[0]
        sens_phot = flux_info.field ("sensitivity")[0]
        ccos.interp1d (wl_phot, sens_phot, wavelength[row], factor)
        factor = np.where (factor <= 0., 1., factor)
        flux[row][:] = net[row] / factor
        error[row][:] = error[row] / factor
    ofd[0].header["fluxcorr"] = "COMPLETE"

    # Compute an array of time-dependent correction factors (a potentially
    # different value at each wavelength), and divide the flux and error by
    # this array.

    if tdscorr == "PERFORM":
        tdstab = reffiles["tdstab"]
        t_obs = (ofd[1].header["expstart"] + ofd[1].header["expend"]) / 2.
        filter = {"opt_elem": opt_elem,
                  "aperture": aperture}
        # First check for dummy rows in the TDS table.  If there is no
        # pedigree column, assume all rows are good (i.e. not dummy).
        dummy = False           # initial value
        for row in range (nrows):
            pharange = cosutil.getPulseHeightRange (ofd[1].header, segment[row])
            # xxx this is temporary
            ref_pharange = cosutil.tempPulseHeightRange (tdstab)
            cosutil.comparePulseHeightRanges (pharange, ref_pharange, tdstab)
            filter["segment"] = segment[row]
            tds_info = cosutil.getTable (tdstab, filter, exactly_one=True)
            names = []
            for name in tds_info.names:
                names.append (name.lower())
            if "pedigree" not in names:
                break
            pedigree = tds_info.field ("pedigree")[0]
            if pedigree == "DUMMY":
                dummy = True
                cosutil.printWarning ("Current row in TDSTAB %s is dummy" % \
                                      tdstab, level=VERBOSE)
                cosutil.printContinuation ("for filter = %s," % \
                                           filter, level=VERBOSE)
                cosutil.printContinuation ("so TDSTAB will not be done.", \
                                           level=VERBOSE)
                break
        if dummy:
            ofd[0].header["tdscorr"] = "SKIPPED"
        else:
            for row in range (nrows):
                filter["segment"] = segment[row]
                # Get an array of factors vs. wavelength at the time of the obs.
                try:
                    tds_results = getTdsFactors (tdstab, filter, t_obs)
                except RuntimeError:    # no matching row in table
                    continue
                (wl_tds, factor_tds) = tds_results
                factor = np.zeros (len (flux[row]), dtype=np.float32)
                # Interpolate factor_tds at each wavelength.
                ccos.interp1d (wl_tds, factor_tds, wavelength[row], factor)
                flux[row][:] /= factor
                error[row][:] /= factor
            ofd[0].header["tdscorr"] = "COMPLETE"

def getTdsFactors (tdstab, filter, t_obs):
    """Get arrays of wavelengths and corresponding TDS factors.

    @param tdstab: name of the time-dependent sensitivity reference table
    @type tdstab: string
    @param filter: dictionary for selecting a row from tdstab
    @type filter: dictionary
    @param t_obs: time of the observation (MJD)
    @type t_obs: float

    @return: (wl_tds, factor_tds), where wl_tds is the array of wavelengths
        from the TDS table, and factor_tds is the corresponding array of
        time-dependent sensitivity factors, evaluated at the time of
        observation from the slope and intercept from the TDS table;
        if the time of observation is outside the range of times in the
        table, factor_tds will be independent of time and equal to the
        factor at the first or last time in the table respectively
    @rtype: tuple, or None
    """

    # Slope and intercept are specified for each of the nt entries in
    # the TIME column and for each of the nwl values in the WAVELENGTH
    # column.  nt and nwl should be at least 1.

    tds_info = cosutil.getTable (tdstab, filter, exactly_one=True)

    fd = pyfits.open (tdstab, mode="readonly")
    ref_time = fd[1].header.get ("ref_time", 0.)        # MJD
    fd.close()

    nwl = tds_info.field ("nwl")[0]
    nt = tds_info.field ("nt")[0]
    wl_tds = tds_info.field ("wavelength")[0]           # 1-D array
    time = tds_info.field ("time")[0]                   # 1-D array
    slope = tds_info.field ("slope")[0]                 # 2-D array
    intercept = tds_info.field ("intercept")[0]         # 2-D array

    # temporary, xxx
    # This section is needed because pyfits currently ignores TDIMi.
    maxt = len (time)
    maxwl = len (wl_tds)
    slope = np.reshape (slope, (maxt, maxwl))
    intercept = np.reshape (intercept, (maxt, maxwl))

    # Find the time interval that includes the time of observation.
    if nt == 1 or t_obs >= time[nt-1]:
        i = nt - 1
    else:
        for i in range (nt-1):
            if t_obs < time[i+1]:
                break

    # The slope in the tdstab is in percent per year.  Convert the time
    # interval to years, and convert the slope to fraction per year.
    # If the time of observation is before the first time in the table or
    # after the last time, the correction factor is to be the factor at
    # the first time or the last time respectively.  This is done by setting
    # delta_t to be the difference from the reference time to the first or
    # last time.
    if t_obs < time[0]:
        delta_t = (time[0] - ref_time) / DAYS_PER_YEAR
    elif t_obs > time[nt-1]:
        delta_t = (time[nt-1] - ref_time) / DAYS_PER_YEAR
    else:
        delta_t = (t_obs - ref_time) / DAYS_PER_YEAR
    slope[:] /= 100.

    # Take the slice [0:nwl] to avoid using elements that may not be valid,
    # and because the array of factors should be the same length as the
    # set of wavelengths that have been specified.
    wl_tds = wl_tds[0:nwl]
    factor_tds = delta_t * slope[i][0:nwl] + intercept[i][0:nwl]

    return (wl_tds, factor_tds)

def updateExtractionKeywords (hdr, segment, slope, height,
                              xd_nominal, xd_locn, xd_offset,
                              b_bkg1, b_bkg2, bkg_height1, bkg_height2):
    """Update keywords giving the locations of extraction regions.

    @param ofd_header: header of the output table
    @type ofd_header: pyfits Header object
    @param segment: FUVA or FUVB; NUVA, NUVB, or NUVC
    @type segment: string
    @param slope: slope of spectrum
    @type slope: float
    @param height: height of extraction box
    @type height: int
    @param xd_nominal: expected location of the spectrum in the cross-
        dispersion direction (where it crosses the middle of the detector)
    @type xd_nominal: float
    @param xd_locn: location of the spectrum in the cross-dispersion
        direction (where it crosses the middle of the detector)
    @type xd_locn: float
    @param xd_offset: difference between where the spectrum was found in the
        cross-dispersion direction and where it was expected (in the sense
        found - expected)
    @type xd_offset: float
    @param b_bkg1: location of first background region (at left edge, as
        read from the reference table)
    @type b_bkg1: float
    @param b_bkg2: location of second background region (at left edge, as
        read from the reference table)
    @type b_bkg2: float
    @param bkg_height1: height of first background region
    @type bkg_height1: int
    @param bkg_height2: height of second background region
    @type bkg_height2: int
    """

    key = "SP_LOC_" + segment[-1]           # SP_LOC_A, SP_LOC_B, SP_LOC_C
    hdr.update (key, xd_locn)
    key = "SP_OFF_" + segment[-1]           # SP_OFF_A, SP_OFF_B, SP_OFF_C
    hdr.update (key, xd_offset)
    key = "SP_NOM_" + segment[-1]           # SP_NOM_A, SP_NOM_B, SP_NOM_C
    hdr.update (key, xd_nominal)
    key = "SP_SLP_" + segment[-1]           # SP_SLP_A, SP_SLP_B, SP_SLP_C
    hdr.update (key, slope)
    key = "SP_HGT_" + segment[-1]           # SP_HGT_A, SP_HGT_B, SP_HGT_C
    hdr.update (key, height)

    # Adjust the values of the background locations to be where the regions
    # cross the middle of the detector.
    if segment[0] == "F":
        tilt_offset = slope * FUV_X / 2.
    else:
        tilt_offset = slope * NUV_X / 2.
    b_bkg1 += tilt_offset
    b_bkg2 += tilt_offset

    key = "B_BKG1_" + segment[-1]
    hdr.update (key, b_bkg1)
    key = "B_BKG2_" + segment[-1]
    hdr.update (key, b_bkg2)
    key = "B_HGT1_" + segment[-1]
    hdr.update (key, bkg_height1)
    key = "B_HGT2_" + segment[-1]
    hdr.update (key, bkg_height2)

def copyKeywordsToInput (output, input, incounts):
    """Copy extraction location keywords to the input headers.

    @param output: name of the output file for 1-D extracted spectra
    @type output: string
    @param input: name of either the flat-fielded count-rate image, or the
        corrtag table
    @type input: string
    @param incounts: name of the file containing the count-rate image,
        or None if input is the corrtag table
    @type incounts: string, or None
    """

    ofd = pyfits.open (output, mode="readonly")
    ifd_e = pyfits.open (input, mode="update")
    if incounts is not None:
        ifd_c = pyfits.open (incounts, mode="update")

    if ofd[0].header["detector"] == "FUV":
        keywords = ["sp_loc_a", "sp_loc_b",
                    "sp_off_a", "sp_off_b",
                    "sp_nom_a", "sp_nom_b",
                    "sp_slp_a", "sp_slp_b",
                    "sp_hgt_a", "sp_hgt_b",
                    "b_bkg1_a", "b_bkg1_b",
                    "b_bkg2_a", "b_bkg2_b",
                    "b_hgt1_a", "b_hgt1_b",
                    "b_hgt2_a", "b_hgt2_b"]
    else:
        keywords = ["sp_loc_a", "sp_loc_b", "sp_loc_c",
                    "sp_off_a", "sp_off_b", "sp_off_c",
                    "sp_nom_a", "sp_nom_b", "sp_nom_c",
                    "sp_slp_a", "sp_slp_b", "sp_slp_c",
                    "sp_hgt_a", "sp_hgt_b", "sp_hgt_c",
                    "b_bkg1_a", "b_bkg1_b", "b_bkg1_c",
                    "b_bkg2_a", "b_bkg2_b", "b_bkg2_c",
                    "b_hgt1_a", "b_hgt1_b", "b_hgt1_c",
                    "b_hgt2_a", "b_hgt2_b", "b_hgt2_c"]

    for key in keywords:
        value = ofd[1].header.get (key, -999.)
        ifd_e[1].header.update (key, value)
        if incounts is not None:
            ifd_c[1].header.update (key, value)

    ofd.close()
    ifd_e.close()
    if incounts is not None:
        ifd_c.close()

def updateCorrtagKeywords (flt, corrtag):
    """Update extraction-location keywords in a corrtag file.

    @param flt: name of an flt file
    @type flt: string
    @param corrtag: name of a corrtag file, to be modified in-place
    @type corrtag: string
    """

    ifd = pyfits.open (flt, mode="readonly")
    ofd = pyfits.open (corrtag, mode="update")

    iphdr = ifd[0].header
    detector = iphdr.get ("detector", "missing")
    if detector == "FUV":
        segment_list = [iphdr["segment"]]
    elif detector == "NUV":
        segment_list = ["NUVA", "NUVB", "NUVC"]
    else:
        segment_list = []

    ihdr = ifd[1].header
    ohdr = ofd[1].header

    for segment in segment_list:
        for key in ["SP_LOC_", "SP_OFF_", "SP_NOM_", "SP_SLP_", "SP_HGT_",
                    "B_BKG1_", "B_BKG2_", "B_HGT1_", "B_HGT2_"]:
            keyword = key + segment[-1]
            if ihdr.has_key (keyword):
                ohdr.update (keyword, ihdr[keyword])

    ofd.close()
    ifd.close()

def updateArchiveSearch (ofd):
    """Update the keywords giving min & max wavelengths, etc.

    @param ofd: output, primary header will be modified in-place
    @type ofd: pyfits HDUList object
    """

    phdr = ofd[0].header
    detector = phdr["detector"]
    outdata = ofd[1].data
    nrows = outdata.shape[0]
    segment = outdata.field ("SEGMENT")
    wavelength = outdata.field ("WAVELENGTH")
    if cosutil.findColumn (outdata, "dq_wgt"):
        dq_wgt = outdata.field ("DQ_WGT")
    else:
        dq_wgt = None

    # First update PLATESC and SPECRES (even if there's no data).
    spwcstab = phdr.get ("spwcstab", "N/A")
    if spwcstab != "N/A":
        opt_elem = phdr.get ("opt_elem", "missing")
        cenwave = phdr.get ("cenwave", "missing")
        aperture = phdr.get ("aperture", "PSA")
        if aperture not in ["PSA", "BOA"]:
            aperture = "PSA"    # override aperture = "WCA" or "FCA"
        filter = {"opt_elem": opt_elem,
                  "cenwave":  cenwave,
                  "segment":  segment[0],
                  "aperture": aperture}
        wcs_info = cosutil.getTable (spwcstab, filter, exactly_one=True)
        cdelt2 = wcs_info.field ("cdelt2")[0] * 3600
        if detector == "NUV":
            cdelt3 = wcs_info.field ("cdelt3")[0] * 3600
            platesc = (cdelt2 + cdelt3) / 2.
        else:
            platesc = cdelt2
        phdr.update ("platesc", platesc)
        specres = wcs_info.field ("specres")
        phdr.update ("specres", specres[0])

    if nrows <= 0 or len (wavelength[0]) < 1:
        return

    nelem = len (wavelength[0])
    # This initial value assumes wavelengths increase with pixel number.
    minwave = wavelength[0][nelem-1]
    maxwave = wavelength[0][0]
    for row in range (nrows):
        if dq_wgt is None:
            good_wl = wavelength[row]
        elif dq_wgt[row].sum (dtype=np.float64) <= 0:
            cosutil.printWarning ("DQ_WGT is all 0 for '%s'" % segment[row])
            good_wl = wavelength[row]
        else:
            good_wl = wavelength[row][dq_wgt[row] > 0.]
        minwave_row = good_wl.min()
        minwave = min (minwave, minwave_row)
        maxwave_row = good_wl.max()
        maxwave = max (maxwave, maxwave_row)

    phdr.update ("MINWAVE", minwave)
    phdr.update ("MAXWAVE", maxwave)
    phdr.update ("BANDWID", maxwave - minwave)
    phdr.update ("CENTRWV", (maxwave + minwave) / 2.)

def fixApertureKeyword (ofd, aperture, detector):
    """Replace aperture in output header if aperture is RelMvReq.

    @param ofd: output primary header, modified in-place
    @type ofd: pyfits HDUList object
    @param aperture: correct aperture name, without -FUV or -NUV
    @type aperture: string
    @param detector: detector name
    @type detector: string
    """

    aperture_hdr = ofd[0].header.get ("aperture", NOT_APPLICABLE)
    if aperture_hdr == "RelMvReq":
        aperture_fixed = aperture + "-" + detector
        ofd[0].header.update ("aperture", aperture_fixed)
        cosutil.printWarning ("APERTURE reset from %s to %s" % \
                (aperture_hdr, aperture_fixed), level=VERBOSE)

def concatenateFUVSegments (infiles, output):
    """Concatenate the 1-D spectra for the two FUV segments into one file.

    @param infiles: list of input file names
    @type infiles: list
    @param output: output file name
    @type output: string
    """

    cosutil.printMsg ("Concatenate " + repr (infiles) + " --> " + output, \
                VERY_VERBOSE)

    a_exists = os.access (infiles[0], os.R_OK)
    b_exists = os.access (infiles[1], os.R_OK)
    if not (a_exists or b_exists):
        cosutil.printWarning ("Neither %s nor %s exists." %
                              (infiles[0], infiles[1]), VERY_VERBOSE)
        return

    rename_file = ""
    if a_exists and not b_exists:
        rename_file = infiles[0]
        missing = infiles[1]
    if b_exists and not a_exists:
        rename_file = infiles[1]
        missing = infiles[0]
    if rename_file:
        cosutil.printWarning ("%s is missing." % missing, VERY_VERBOSE)
        cosutil.renameFile (rename_file, output)
        return

    ifd_0 = pyfits.open (infiles[0], mode="readonly")
    ifd_1 = pyfits.open (infiles[1], mode="readonly")

    # Make sure we know which files are for segments A and B respectively,
    # and then use seg_a and seg_b instead of ifd_0 and ifd_1.
    if ifd_0[0].header["segment"] == "FUVA":
        seg_a = ifd_0
    elif ifd_1[0].header["segment"] == "FUVA":
        seg_a = ifd_1
    else:
        seg_a = None
    if ifd_0[0].header["segment"] == "FUVB":
        seg_b = ifd_0
    elif ifd_1[0].header["segment"] == "FUVB":
        seg_b = ifd_1
    else:
        seg_b = None
    if seg_a is None or seg_b is None:
        cosutil.printError ("files are " + infiles[0] + " " + infiles[1])
        raise RuntimeError, \
            "Files to concatenate must be for segments FUVA and FUVB."

    if seg_a[1].data is None:
        nrows_a = 0
    else:
        nrows_a = seg_a[1].data.shape[0]

    if seg_b[1].data is None:
        nrows_b = 0
    else:
        nrows_b = seg_b[1].data.shape[0]

    # Take output column definitions from input for segment A.
    cd = pyfits.ColDefs (seg_a[1])
    hdu = pyfits.new_table (cd, seg_a[1].header, nrows=nrows_a+nrows_b)

    # Copy data from input to output.
    copySegments (seg_a[1].data, nrows_a, seg_b[1].data, nrows_b, hdu.data)

    # Include segment-specific keywords from segment B.  The strings in
    # segment_specific_keywords (which is defined in calcosparam.py) use "X"
    # as the character to be replaced by "b" to get the actual keyword name
    # for segment B.
    for key in segment_specific_keywords:
        keyword = key.replace ("X", "b")
        if seg_b[1].header.has_key (keyword):
            hdu.header.update (keyword, seg_b[1].header.get (keyword, -1.0))

    exptimea = seg_a[1].header.get ("exptimea",
                                    default=seg_a[1].header["exptime"])
    exptimeb = seg_b[1].header.get ("exptimeb",
                                    default=seg_b[1].header["exptime"])
    hdu.header.update ("exptime", max (exptimea, exptimeb))

    neventsa = seg_a[1].header.get ("neventsa",
                                    seg_a[1].header.get ("nevents", 0))
    neventsb = seg_b[1].header.get ("neventsb",
                                    seg_b[1].header.get ("nevents", 0))
    hdu.header.update ("nevents", neventsa + neventsb)

    # If one of the segments has no data, use the other segment for the
    # primary header.  This is so the calibration switch keywords in the
    # output x1d file will be set appropriately.
    if nrows_a > 0 or nrows_b == 0:
        phdu = seg_a[0]
    else:
        phdu = seg_b[0]
    ofd = pyfits.HDUList (phdu)
    cosutil.updateFilename (ofd[0].header, output)
    if a_exists and b_exists and nrows_a > 0 and nrows_b > 0:
        # we now have both segments
        ofd[0].header.update ("segment", "BOTH")
    ofd.append (hdu)

    # Update the "archive search" keywords.
    updateArchiveSearch (ofd)

    ofd.writeto (output, output_verify="fix")
    ifd_0.close()
    ifd_1.close()

    if phdu.header["statflag"]:
        cosutil.doSpecStat (output)

def copySegments (data_a, nrows_a, data_b, nrows_b, outdata):
    """Copy the two input tables to the output table.

    @param data_a: data block for segment A (may have no data)
    @type data_a: pyfits recarray object
    @param nrows_a: length of data_a (may be zero)
    @type nrows_a: int
    @param data_b: data block for segment B (may have no data)
    @type data_b: pyfits recarray object
    @param nrows_b: length of data_b (may be zero)
    @type nrows_b: int
    @param outdata: data block with nrows_a + nrows_b rows
    @type outdata: pyfits recarray object
    """

    n = 0
    for i in range (nrows_a):
        outdata[n] = data_a[i]
        n += 1
    for i in range (nrows_b):
        outdata[n] = data_b[i]
        n += 1

def recomputeWavelengths (input):
    """Update the wavelength column in a wavecal x1d table.

    The values in the wavelength column will be recomputed (updated in-place)
    to include the shift in the dispersion direction, as read from the
    shift1[abc] keywords.

    If wavecorr is already COMPLETE, this function returns without doing
    anything; otherwise, after correcting the wavelengths, wavecorr will be
    set to COMPLETE.  (Wavecal processing was done earlier, but it was not
    really finished until this function was called.)  The check on wavecorr
    is necessary because for FUV data the list of files may include the
    x1d file name twice, once for each segment.

    @param input: name of an x1d file for a wavecal
    @type input: string
    """

    fd = pyfits.open (input, mode="update")
    phdr = fd[0].header
    hdr = fd[1].header
    if hdr["naxis2"] == 0:
        fd.close()
        return
    cosutil.printMsg ("Updating wavelengths in %s" % input, VERY_VERBOSE)

    data = fd[1].data

    info = getinfo.getGeneralInfo (phdr, hdr)
    disptab = cosutil.expandFileName (phdr["disptab"])

    segment_col = data.field ("SEGMENT")
    nelem_col = data.field ("NELEM")
    wl_col = data.field ("WAVELENGTH")

    # To correct for the extra pixels (if any) in the dispersion direction.
    x_offset = hdr.get ("x_offset", 0)

    for row in range (len (data)):

        segment = segment_col[row]
        filter = {"segment": segment,
                  "opt_elem": info["opt_elem"],
                  "cenwave": info["cenwave"],
                  "aperture": "WCA",
                  "fpoffset": info["fpoffset"]}
        disp_rel = dispersion.Dispersion (disptab, filter)
        if not disp_rel.isValid():
            continue
        key = "shift1" + segment[-1]
        shift1 = hdr.get (key, 0.)

        # 'pixel' is an array of pixel coordinates.
        nelem = nelem_col[row]
        pixel = np.arange (nelem, dtype=np.float64)

        pixel -= shift1
        pixel -= x_offset
        wl_col[row][0:nelem] = disp_rel.evalDisp (pixel)
        disp_rel.close()

    phdr.update ("WAVECORR", "COMPLETE")

    fd.close()
