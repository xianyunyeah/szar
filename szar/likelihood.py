import numpy as np
from szar.counts import ClusterCosmology,Halo_MF
import emcee
from nemo import simsTools
from scipy import special,stats
from astropy.io import fits
from astLib import astWCS
from configparser import SafeConfigParser
from orphics.tools.io import dictFromSection
import cPickle as pickle
import matplotlib.pyplot as plt

#import time

def read_MJH_noisemap(noiseMap,maskMap):
    #Read in filter noise map
    img = fits.open(noiseMap)
    rmsmap=img[0].data
    #Read in mask map
    img2 = fits.open(maskMap)
    mmap=img2[0].data
    #return the filter noise map for pixels in the mask map that = 1
    return rmsmap*mmap

def read_clust_cat(fitsfile):
    list = fits.open(fitsfile)
    data = list[1].data
    ra = data.field('RADeg')
    dec = data.field('DECDeg')
    z = data.field('M500_redshift')
    Y0 = data.field('fixed_y_c')
    Y0err = data.field('fixed_err_y_c')
    return ra,dec,z,Y0,Y0err

class clusterLike:
    def __init__(self,iniFile,expName,gridName,parDict,nemoOutputDir,noiseFile):
        
        Config = SafeConfigParser()
        Config.optionxform=str
        Config.read(iniFile)

        self.fparams = {}
        for (key, val) in Config.items('params'):
            if ',' in val:
                param, step = val.split(',')
                self.fparams[key] = float(param)
            else:
                self.fparams[key] = float(val)

        bigDataDir = Config.get('general','bigDataDirectory')
        self.clttfile = Config.get('general','clttfile')
        self.constDict = dictFromSection(Config,'constants')
        version = Config.get('general','version')
        
        self.mgrid,self.zgrid,siggrid = pickle.load(open(bigDataDir+"szgrid_"+expName+"_"+gridName+ "_v" + version+".pkl",'rb'))
        self.cc = ClusterCosmology(self.fparams,self.constDict,clTTFixFile=self.clttfile)
        self.HMF = Halo_MF(self.cc,self.mgrid,self.zgrid)

        self.diagnosticsDir=nemoOutputDir+"diagnostics" 
        self.filteredMapsDir=nemoOutputDir+"filteredMaps"
        self.tckQFit=simsTools.fitQ(parDict, self.diagnosticsDir, self.filteredMapsDir)
        FilterNoiseMapFile = nemoOutputDir + noiseFile
        MaskMapFile = self.diagnosticsDir + '/areaMask.fits'
        clust_cat = nemoOutputDir + 'ACTPol_mjh_cluster_cat.fits'

        self.rms_noise_map  = read_MJH_noisemap(FilterNoiseMapFile,MaskMapFile)
        self.wcs=astWCS.WCS(FilterNoiseMapFile) 
        self.clst_RA,self.clst_DEC,self.clst_z,self.clst_y0,self.clst_y0err = read_clust_cat(clust_cat)
        self.clst_xmapInd,self.clst_ymapInd = self.Find_nearest_pixel_ind(self.clst_RA,self.clst_DEC)

        self.qmin = 5.6
        self.num_noise_bins = 20
        self.area_rads = 987.5/41252.9612
        self.LgY = np.arange(-6,-3,0.05)

        count_temp,bin_edge =np.histogram(np.log10(self.rms_noise_map[self.rms_noise_map>0]),bins=self.num_noise_bins)
        self.frac_of_survey = count_temp*1.0 / np.sum(count_temp)
        self.thresh_bin = 10**((bin_edge[:-1] + bin_edge[1:])/2.)

    def alter_fparams(self,fparams,parlist,parvals):
        for k,parvals in enumerate(parvals):
            fparams[parlist[k]] = parvals
        return fparams

    def Find_nearest_pixel_ind(self,RADeg,DECDeg):
        xx = np.array([])
        yy = np.array([])
        for ra, dec in zip(RADeg,DECDeg):
            x,y = self.wcs.wcs2pix(ra,dec)
            np.append(xx,np.round(x))
            np.append(yy,np.round(y))
        #return [np.round(x),np.round(y)]
        return xx,yy

    def PfuncY(self,YNoise,M,z_arr,param_vals):
        LgY = self.LgY
        
        P_func = np.outer(M,np.zeros([len(z_arr)]))
        M_arr =  np.outer(M,np.ones([len(z_arr)]))

        for i in range(z_arr.size):
            P_func[:,i] = self.P_of_gt_SN(LgY,M_arr[:,i],z_arr[i],YNoise,param_vals)
        return P_func

    def P_Yo(self, LgY, M, z,param_vals):
        #M500c has 1/h factors in it
        Ma = np.outer(M,np.ones(len(LgY[0,:])))
        Ytilde, theta0, Qfilt =simsTools.y0FromLogM500(np.log10(param_vals['massbias']*Ma/(param_vals['H0']/100.)), z, self.tckQFit,sigma_int=param_vals['scat'])#,B0=param_vals['yslope'])#,tenToA0=YNorm)
        Y = 10**LgY
        numer = -1.*(np.log(Y/Ytilde))**2
        ans = 1./(param_vals['scat'] * np.sqrt(2*np.pi)) * np.exp(numer/(2.*param_vals['scat']**2))
        return ans

    def Y_erf(self,Y,Ynoise):
        qmin = self.qmin  # fixed 
        ans = 0.5 * (1. + special.erf((Y - qmin*Ynoise)/(np.sqrt(2.)*Ynoise)))
        return ans

    def P_of_gt_SN(self,LgY,MM,zz,Ynoise,param_vals):
        Y = 10**LgY
        sig_thresh = np.outer(np.ones(len(MM)),self.Y_erf(Y,Ynoise))
        LgYa = np.outer(np.ones(len(MM)),LgY)
        P_Y = self.P_Yo(LgYa,MM,zz,param_vals)
        ans = np.trapz(P_Y*sig_thresh,LgY,np.diff(LgY),axis=1)
        return ans
    
    def q_prob (self,q,LgY,YNoise):
        Y = 10**(LgY)
        ans = gaussian(q,Y/YNoise,1.)
        return ans

    def Ntot_survey(self,int_HMF,fsky,Ythresh,param_vals):

        z_arr = self.HMF.zarr.copy()        
        Pfunc = self.PfuncY(Ythresh,self.HMF.M.copy(),z_arr,param_vals)
        dn_dzdm = int_HMF.dn_dM(int_HMF.M200,200.)

        N_z = np.trapz(dn_dzdm*Pfunc,dx=np.diff(int_HMF.M200,axis=0),axis=0)
        Ntot = np.trapz(N_z*int_HMF.dVdz,dx=np.diff(z_arr))*4.*np.pi*fsky
        return Ntot

    def lnprior(self,theta):
        a1,a2 = theta
        if  1 < a1 < 5 and  1 < a2 < 2:
            return 0
        return -np.inf

    def lnlike(self,theta,parlist,cluster_data):
        
        param_vals = self.alter_fparams(self.fparams,parlist,theta)
        int_cc = ClusterCosmology(param_vals,self.constDict,clTTFixFile=self.clttfile) # internal HMF call
        int_HMF = Halo_MF(int_cc,self.mgrid,self.zgrid) # internal HMF call

        Ntot = 0.
        for i in range(len(self.frac_of_survey)):
             Ntot += self.Ntot_survey(int_HMF,self.area_rads*self.frac_of_survey[i],self.thresh_bin[i],param_vals)

        Nind = 0
        for i in xrange(len(cluster_data)):
            N_per = 1.
            Nind = Nind + np.log(N_per) 
        return -Ntot #* Nind

    def lnprob(self,theta, inter, mthresh, zthresh):
        lp = self.lnprior(theta, mthresh, zthresh)
        if not np.isfinite(lp):
            return -np.inf
        return lp + self.lnlike(theta, inter)

#Functions from NEMO
#y0FromLogM500(log10M500, z, tckQFit, tenToA0 = 4.95e-5, B0 = 0.08, Mpivot = 3e14, sigma_int = 0.2)
#fitQ(parDict, diagnosticsDir, filteredMapsDir)

    #self.diagnosticsDir=nemoOutputDir+os.path.sep+"diagnostics"
    
    #filteredMapsDir=nemoOutputDir+os.path.sep+"filteredMaps"
    #self.tckQFit=simsTools.fitQ(parDict, self.diagnosticsDir, filteredMapsDir)
