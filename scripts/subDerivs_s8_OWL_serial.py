from orphics.tools.io import listFromConfig
import numpy as np
import time
import os

#expList = ['SO-3m','SO-5m','SO-6m','SO-7m','S4-3m','S4-5m','S4-6m','S4-7m','S4-5m-noatm','S4-6m-noatm','S4-7m-noatm','SO-5m-noatm','SO-6m-noatm','SO-7m-noatm','SO-3m-noatm','S4-3m-noatm']

expList = ['S4-1.0-CDT','S4-1.5-CDT']

calList = ['owl2']
#['owl1']

#calList = ['owl1-planck']




from ConfigParser import SafeConfigParser 
iniFile = "input/pipeline.ini"
Config = SafeConfigParser()
Config.optionxform=str
Config.read(iniFile)
bigDataDir = Config.get('general','bigDataDirectory')
version = Config.get('general','version')




for exp in expList:

    for cal in calList:

        gridName = "grid-"+cal

        zs = listFromConfig(Config,gridName,'zrange')
        z_edges = np.arange(zs[0],zs[1]+zs[2],zs[2])

        numCores = z_edges.size
        
        massGridName = bigDataDir+"lensgrid_"+gridName+"_"+cal+".pkl"


        cmd = "python bin/makeS8Derivs_serial.py "+exp+" "+gridName+" "+cal+" "+massGridName
        
        print cmd
        os.system(cmd)
        time.sleep(0.3)

