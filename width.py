"""
Class to derive a rotation velocity profile by minimizing the width of a line.
This implicitly assumes a Gaussian line profile which may not be correct for
optically thick lines or those with significant structure due to the velocity
profile.
"""

import matplotlib.pyplot as plt
from prettyplots.prettyplots import running_mean
from imgcube.imagecube import imagecube
from scipy.interpolate import interp1d
from scipy.optimize import curve_fit
from scipy.optimize import minimize
import flaring.cube as flaring
import numpy as np


class linecube:

    def __init__(self, path, inc=0.0, dist=122., x0=0.0, y0=0.0,
                 orientation='east', flared=True, nsigma=3, downsample=1,
                 rmin=30., rmax=350., nbins=30., smooth=False, verbose=True):
        """
        Initial instance of a line cube based on `imagecube`. The cube must be
        rotated such that the major axis is aligned with the x-axis.

        - Input Variables -

        path:           Relative path to the fits cube.
        inc:            Inclination of the disk in [degrees].
        dist:           Distance to disk in [pc].
        x0, y0:         Offset of star in [arcseconds].
        orientation:    Direction of the blue shifted half of the disk. This is
                        used to calculate the position angles of the pixels.
        flared:         Boolean, if True, account for the flared emission
                        surface when binning the annuli.
        nsigma:         Clip all voxels below nsigma * rms when calculating the
                        emission surface.
        downsample:     Number of channels to average over when calculating the
                        emission surface.
        rmin:           Minimum radius for the surface profile in [au].
        rmax:           Maximum radius for the surface profile in [au].
        nbins:          Number of radial points between rmin and rmax.
        smooth:         Number of points used in a running mean to smooth data.
        verbose:        Boolean describing if output message should be used.
        """

        self.path = path
        self.file = path.split('/')[-1]
        self.cube = imagecube(path)
        self.velax = self.cube.velax
        self.verbose = verbose
        self.dist = dist
        self.inc = inc

        # Orientation of the disk. Note that this is not the true position
        # angle of the disk, rather just used interally.

        self.x0, self.y0 = x0, y0
        if orientation.lower() not in ['east', 'west']:
            raise ValueError("Orientation must be 'east' or 'west'.")
        self.orientation = orientation.lower()
        self.pa = 0.0 if self.orientation == 'east' else 180.
        self.rvals, self.tvals = self.cube._deproject(x0=self.x0,
                                                      y0=self.y0,
                                                      inc=self.inc,
                                                      pa=self.pa)

        # Use the flaring module to calculate the emission surface.
        # We only need z(r) so everything else is forgotten.

        self.nsigma = nsigma
        self.downsample = downsample
        self.rmin, self.rmax, self.nbins = rmin, rmax, nbins
        self.smooth = smooth
        if self.flaring:
            if self.verbose:
                print("Calculating emission surface...")
            self.surface = self.get_emission_surface()
            if self.verbose:
                print("Done.")
        else:
            self.surface = 0.0

        return

    def get_rotation_profile(self, rpnts=None, width=None, errors=False):
        """
        Derive the rotation profile by minimizing the width of the average of
        the deprojected spectra. The inital value is found by using scipy's
        minimize function which is relatively fast.

        If errors are wanted, thess values are used as the models for emcee
        runs which estimate the posterior on vrot. This is relatively time
        consuming so make sure that the simple minimize approach works well
        first.

        - Input Variables -

        rpnts:      Array of radial points to calculate the rotation profile.
                    If None then will use the radial sampling of the surface
                    profile.
        width:      Width of the annuli in [arcsec]. If None is specified, will
                    use the spacing of rpnts.
        errors:     If True, use an MCMC approach to estimate uncertainties on
                    vrot. This will take much longer.

        - Output -

        vrot:       Rotation profile in [m/s] at the sampled points. If errors
                    is True, this is a [3 x len(rpnts)] array with the
                    [16, 50, 84] percentiles for each radial point, otherwise
                    it is just a len(rpnts) array.
        """

        if errors:
            raise NotImplementedError("Wait.")

        # Define the radial sampling points and bin the pixels.
        if rpnts is None:
            rpnts = self.surface.x
        if width is None:
            width = np.mean(np.diff(rpnts))
        rbins = np.linspace(rpnts[0] - 0.5 * width,
                            rpnts[-1] + 0.5 * width,
                            rpnts.size + 1)
        rflat, tflat = self.rvals.flatten(), self.tvals.flatten()
        dflat = self.cube.data.reshape((self.cube.data.shape[0], -1)).T
        ridxs = np.digitize(rflat, rbins)

        # Use scipy.optimize.minimize to find the rortation velocity at each
        # radial point. Define a function to minimize. TODO: Find out how to
        # make this a separate function and not an embedded one.

        def to_minimize(vrot, spectra, angles):
            """Function to minimize."""
            deprojected = self._spectral_deproject(vrot, spectra, angles)
            return self._fit_width(deprojected)

        p0 = []
        for idx, radius in enumerate(rpnts):
            spectra = dflat[ridxs == idx + 1]
            angles = tflat[ridxs == idx + 1]
            vrot = self._estimate_vrot(spectra)
            res = minimize(to_minimize, vrot, args=(spectra, angles),
                           method='Nelder-Mead')
            p0.append(res.x)

        return np.squeeze(p0)

    def get_emission_surface(self):
        """
        Derive the emission surface profile. See flaring.cube.linecube for
        more help.

        - Output -

        surface:    Interpolation function for z(r), with both r and z in [au].
                    The values are linearly interpolated and extrapolated
                    beyond the bounds.
        """
        cube = flaring.linecube(self.path, inc=self.inc, dist=self.dist,
                                nsigma=self.nsigma, downsample=self.downsample)
        r, z, _ = cube.emission_surface(rmin=self.rmin, rmax=self.rmax,
                                        nbins=self.nbins)

        # Apply a running mean to smooth out the profile then return a function
        # to interpolate the value.
        if self.smooth > 1:
            z = np.squeeze([running_mean(zz) for zz in z])
        return interp1d(r, z[1], fill_value='extrapolate')

    def _spectral_deproject(self, vrot, spectra, angles):
        """
        Deperoject the spectra to a common center. It is assumed that all share
        the same velocity axis: self.cube.velax.

        - Input Variables -

        vrot:       Rotation velocity used for the deprojection in [m/s].
        spectra:    Array of spectra to deproject.
        angles:     Position angle of the pixel in [radians], measured East
                    from the blue-shifted major axis.

        - Output -

        deproj:     Average of all deprojected spectra.
        """
        deproj = [np.interp(self.velax, self.velax + vrot * np.cos(t), spec)
                  for spec, t in zip(spectra, angles)]
        return np.average(deproj, axis=0)

    def _estimate_vrot(self, spectra):
        """Estimate the rotation velocity from line peaks."""
        centers = np.take(self.velax, np.argmax(spectra, axis=1))
        vmin, vmax = centers.min(), centers.max()
        vlsr = np.average([vmin, vmax])
        return np.average([vlsr - vmin, vmax - vlsr])

    def plot_emission_surface(self, ax=None):
        """Plot the emission surface."""
        if ax is None:
            fig, ax = plt.subplots()
        ax.plot(self.surface.x, self.surface.y)
        ax.set_xlabel('Radius (au)')
        ax.set_ylabel('Height (au)')
        return ax

    def _fit_width(self, spectrum, failed=1e20):
        """Fit the spectrum with a Gaussian function."""
        Tb = spectrum.max()
        x0 = self.velax[spectrum.argmax()]
        dV = np.trapz(spectrum, self.velax) / Tb / np.sqrt(2. * np.pi)
        try:
            popt, _ = curve_fit(gaussian, self.velax, spectrum,
                                maxfev=10000, p0=[x0, dV, Tb])
            return popt[1]
        except:
            return failed


def gaussian(x, x0, dx, A):
    """Gaussian function with Doppler width."""
    return A * np.exp(-np.power((x-x0) / dx, 2))