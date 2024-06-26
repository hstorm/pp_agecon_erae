# %%
"""Example linear model in PP

Hugo Storm Feb 2024

"""
import os
import sys
import arviz as az
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import seaborn as sns

import jax 
from jax import random

import numpyro
import numpyro.distributions as dist
from numpyro.infer import MCMC, NUTS, Predictive

if len(jax.devices(backend='gpu'))>0:
    numpyro.set_platform("gpu")
else:
    numpyro.set_platform("cpu")
    
az.style.use("arviz-darkgrid")

wd = '/workspaces/pp_agecon_erae'
os.chdir(wd)
sys.path.append(wd)

# Make sure that numpyro is the correct version
assert numpyro.__version__.startswith("0.13.0")

plt.style.use('default')
import matplotlib as mpl
mpl.rcParams['figure.dpi'] = 300

# %%
# Set seed for reproducibility
rng_key = random.PRNGKey(1)
np.random.seed(0)

# %%
# Load data
from util.load_yield_data import getData
dfL_train, dfL_test, lstCatCrop, lstCatNUTS3, lstSmi25, lstSmi180, scale_train = getData()   

lstColX = ['bodenzahl_scaled'] 

dfWheat_train = dfL_train.loc[dfL_train['crop']=='Winterweizen',:]
    
Soil = dfL_train.loc[dfL_train['crop']=='Winterweizen','bodenzahl_scaled'].values 
Yield = dfL_train.loc[dfL_train['crop']=='Winterweizen','yield_scaled'].values    

# %%
print(f"SoilRating [0-100]: Mean={scale_train['bodenzahl_mean']:.2f}, Std={scale_train['bodenzahl_std']:.2f}")
print(f"WinterWheatYield: Mean={scale_train['Winterweizen_yield_mean']:.2f}dt, Std={scale_train['Winterweizen_yield_std']:.2f}dt")

# %%
# =============================================================================
# Define most basic linear regression model
# =============================================================================
def model(Soil, Yield=None):
    beta = numpyro.sample('beta', dist.Normal(0,1))
    sigma = numpyro.sample('sigma', dist.Exponential(1))
    numpyro.sample('Yield',dist.Normal(Soil*beta,sigma), obs=Yield)
    
# Example of a linear regression in matrix notation, 
# same as "model()" but suitable for more then one explanatory variable     
def model_matrix(X, Y=None):
    beta = numpyro.sample('beta', dist.Normal(0,1).expand([X.shape[1]]))
    sigma = numpyro.sample('sigma', dist.Exponential(4))
    numpyro.sample('Y',dist.Normal(X @ beta,sigma), obs=Y)

# Same model as above, but with std of beta prior as a parameter
def model_sigma_b(Soil, sigma_b, Yield=None):
    beta = numpyro.sample('beta', dist.Normal(0,sigma_b))
    sigma = numpyro.sample('sigma', dist.Exponential(1))
    numpyro.sample('Yield',dist.Normal(Soil*beta,sigma), obs=Yield)
    
# Same model as above, but with yield as a student-t distribution and truncated at zero
lowtrunc_scale = (0-scale_train['Winterweizen_yield_mean'])/scale_train['Winterweizen_yield_std']
def model_trunc(Soil, sigma_b, Yield=None):
    beta = numpyro.sample('beta', dist.Normal(0,sigma_b))
    sigma = numpyro.sample('sigma', dist.Exponential(1))
    df = 5 # degrees of freedom for student-t distribution
    # Truncate studentT distribution
    numpyro.sample('Yield',dist.LeftTruncatedDistribution(
        dist.StudentT(df,Soil*beta,sigma),low=lowtrunc_scale), obs=Yield)
    # Alternative use a truncated normal instead
    # numpyro.sample('Yield',dist.TruncatedNormal(Soil*beta,sigma,low=lowtrunc_scale), obs=Yield)


# %%
# =============================================================================
# Prior sampling
# =============================================================================
model = model_sigma_b
# model = model_trunc # Change here to use the truncated model

nPriorSamples = 1000 # Number of prior samples
# Perform prior sampling for different values of sigma_b
lstRes = []
for sigma_b in [1,5]:
    # =============================================================================
    # Sample from prior
    # =============================================================================
    rng_key, rng_key_ = random.split(rng_key)
    prior_predictive = Predictive(model, num_samples=nPriorSamples)
    prior_samples = prior_predictive(rng_key_,Soil=Soil, sigma_b=sigma_b)
    
    # =============================================================================
    # Estimate model using numpyro MCMC
    # =============================================================================
    print(f"Estimate model with sigma_b={sigma_b}")
    rng_key, rng_key_ = random.split(rng_key)
    kernel = NUTS(model)
    mcmc = MCMC(kernel, num_samples=800, num_warmup=1000, num_chains=2)
    mcmc.run(rng_key_, Soil=Soil, sigma_b=sigma_b, Yield=Yield)
    mcmc.print_summary()

    # Inspect MCMC sampling using arviz    
    # azMCMC = az.from_numpyro(mcmc)
    # azMCMC= azMCMC.assign_coords({'b_dim_0':lstColX})
    # az.summary(azMCMC)
    # az.plot_trace(azMCMC);

    # Get posterior samples
    post_samples = mcmc.get_samples()

    # Append results to list
    lstRes.append({
        'post_samples':post_samples,
        'prior_samples':prior_samples,
        'sigma_b':sigma_b
    })
# %%
# ================================
# Plot figures 2 and 3
# ================================
fig2 = plt.figure(constrained_layout=True,figsize=(15, 10))
(subfig2top, subfig2bot) = fig2.subfigures(2, 1) 
axFig2 = np.array([subfig2top.subplots(1, 2),
                   subfig2bot.subplots(1, 2)])
subfig2top.suptitle('Prior samples for yields',fontsize=20,fontweight="bold")             
subfig2bot.suptitle('Prior samples of regression lines',fontsize=20,fontweight="bold")    

fig3 = plt.figure(constrained_layout=True,figsize=(15, 10))
(subfig3top, subfig3bot) = fig3.subfigures(2, 1)
axFig3 = np.array([subfig3top.subplots(1, 2),
                   subfig3bot.subplots(1, 2)])
subfig3top.suptitle('Posterior and Prior densities',fontsize=20,fontweight="bold")   
subfig3bot.suptitle('Posterior regression lines',fontsize=20,fontweight="bold") 

for icol, res in enumerate(lstRes):
    prior_samples = res['prior_samples']
    post_samples = res['post_samples']
    sigma_b = res['sigma_b']
    
    # Plot prior samples
    axFig2[0,icol].hist((prior_samples['Yield'].flatten()[~np.isinf(prior_samples['Yield'].flatten())]
                *scale_train['Winterweizen_yield_std']
                +scale_train['Winterweizen_yield_mean'])/10,
            bins=100, density=True, color='grey');
    axFig2[0,icol].set_title(fr'$\beta$~Normal(0,{sigma_b})', fontsize=20)
    axFig2[0,icol].set_xlabel('Yield [t/ha]', fontsize=20)
    axFig2[0,icol].set_ylabel('Density', fontsize=20)
    # Set tick font size
    for label in (axFig2[0,icol].get_xticklabels() + axFig2[0,icol].get_yticklabels()):
        label.set_fontsize(20)
    axFig2[0,icol].spines['right'].set_visible(False)
    axFig2[0,icol].spines['top'].set_visible(False)
    
    # Plot regression lines
    x_range_scaled = np.linspace(-5,5,100)
    x_mean_scaled = Soil.mean(axis=0)
    x_plot = np.repeat(x_mean_scaled.reshape(1,-1),100,axis=0)
    x_plot[:,0] = x_range_scaled
    x_range = x_range_scaled*scale_train['bodenzahl_std']+scale_train['bodenzahl_mean']
    for i in range(1,300):
        y_hat_scaled = x_plot @ prior_samples['beta'][i].reshape(-1,1) 
        
        y_hat = y_hat_scaled*scale_train['Winterweizen_yield_std']+scale_train['Winterweizen_yield_mean']

        axFig2[1,icol].plot(x_range,y_hat/10,color='k',alpha=0.2)

    axFig2[1,icol].set_title(fr'$\beta$~Normal(0,{sigma_b})', fontsize=20)    
    axFig2[1,icol].set_xlabel('Soil Rating', fontsize=20)
    axFig2[1,icol].set_ylabel('Yield [t/ha]', fontsize=20)
    axFig2[1,icol].set_xlim([30,70])
    if sigma_b==1:
        axFig2[1,icol].set_ylim([0,15])
    else:
        axFig2[1,icol].set_ylim([-20,40])
        
    axFig2[1,icol].spines['right'].set_visible(False)
    axFig2[1,icol].spines['top'].set_visible(False)
    
    sns.rugplot(data=Soil*scale_train['bodenzahl_std']+scale_train['bodenzahl_mean'], 
            ax=axFig2[1,icol], color='grey')    
    # Set tick font size
    for label in (axFig2[1,icol].get_xticklabels() + axFig2[1,icol].get_yticklabels()):
        label.set_fontsize(20)
        
    # Plot posterior samples

    # fig, axFig3[0,icol] = plt.subplots(1, 1, figsize=(6, 4))
    axFig3[0,icol].hist(prior_samples['beta'],bins=100,density=True, label='prior', color='grey');
    axFig3[0,icol].hist(post_samples['beta'],bins=100,density=True, label='posterior', color='black');
    axFig3[0,icol].set_title(fr'$\beta$~Normal(0,{sigma_b})', fontsize=20)
    axFig3[0,icol].set_xlabel(fr"$\beta$", fontsize=20)
    axFig3[0,icol].set_xlim([-1,1])
    axFig3[0,icol].set_ylabel('Density', fontsize=20)
    axFig3[0,icol].legend(frameon=False, fontsize=20)
    axFig3[0,icol].spines['right'].set_visible(False)
    axFig3[0,icol].spines['top'].set_visible(False)
    
    for label in (axFig3[0,icol].get_xticklabels() + axFig3[0,icol].get_yticklabels()):
        label.set_fontsize(20)
        
    # Plot regression lines
    x_range_scaled = np.linspace(-5,5,100)
    x_mean_scaled = Soil.mean(axis=0)
    x_plot = np.repeat(x_mean_scaled.reshape(1,-1),100,axis=0)
    x_plot[:,0] = x_range_scaled

    x_range = x_range_scaled*scale_train['bodenzahl_std']+scale_train['bodenzahl_mean']
    for i in range(1,300):
        y_hat_scaled = x_plot @ post_samples['beta'][i].reshape(-1,1) 
        y_hat = y_hat_scaled*scale_train['Winterweizen_yield_std']+scale_train['Winterweizen_yield_mean']
        axFig3[1,icol].plot(x_range,y_hat/10,color='k',alpha=0.2)

    axFig3[1,icol].set_title(fr'$\beta$~Normal(0,{sigma_b})', fontsize=20)    
    axFig3[1,icol].set_xlabel('Soil Rating', fontsize=20)
    axFig3[1,icol].set_ylabel('Yield [t/ha]', fontsize=20)
    axFig3[1,icol].set_xlim([30,70])
    for label in (axFig3[1,icol].get_xticklabels() + axFig3[1,icol].get_yticklabels()):
        label.set_fontsize(20)
    
    axFig3[1,icol].spines['right'].set_visible(False)
    axFig3[1,icol].spines['top'].set_visible(False)

    sns.rugplot(data=Soil*scale_train['bodenzahl_std']+scale_train['bodenzahl_mean'], 
                ax=axFig3[1,icol], color='grey')    

fig2.show()
fig3.show()
fig2.savefig(f'figures/linReg_figure2.png',dpi=300)   
fig3.savefig(f'figures/linReg_figure3.png',dpi=300)   
# %%
