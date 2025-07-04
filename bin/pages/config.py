import json
import time
import pathlib
import streamlit as st
import sys,os
import inspect
import pyflowchart as pfc
import uuid
import copy
import streamlit.components.v1 as components
import shutil
import functools as ft

sys.path.append('.')
import model_discovery.utils as U
import bin.app_utils as AU
import numpy as np
import pandas as pd

from model_discovery.agents.flow.gau_flows import DesignModes,RunningModes
from model_discovery.evolution import DEFAULT_PARAMS,DEFAULT_N_SOURCES,BUDGET_TYPES,DEFAULT_RANDOM_ALLOW_TREE
from model_discovery.agents.roles.selector import DEFAULT_SEED_DIST,SCHEDULER_OPTIONS,RANKING_METHODS,MERGE_METHODS,\
    DEFAULT_RANKING_ARGS,DEFAULT_QUADRANT_ARGS,DEFAULT_DESIGN_EXPLORE_ARGS,DEFAULT_VERIFY_EXPLORE_ARGS,\
        SELECT_METHODS,VERIFY_STRATEGIES,DEFAULT_SELECT_METHOD,DEFAULT_VERIFY_STRATEGY,DEFAULT_N_SEEDS_SETTINGS,DEFAULT_N_SEEDS_DIST
from model_discovery.system import DEFAULT_AGENTS,DEFAULT_MAX_ATTEMPTS,DEFAULT_TERMINATION,DEFAULT_USE_UNLIMITED_PROMPT,\
    DEFAULT_THRESHOLD,DEFAULT_SEARCH_SETTINGS,DEFAULT_NUM_SAMPLES,DEFAULT_MODE,DEFAULT_UNITTEST_PASS_REQUIRED,\
    AGENT_OPTIONS,DEFAULT_AGENT_WEIGHTS,DEFAULT_AGENT_WEIGHTS,DEFAULT_CROSSOVER_NO_REF,DEFAULT_MUTATION_NO_TREE,DEFAULT_SCRATCH_NO_TREE
from model_discovery.agents.search_utils import EmbeddingDistance,DEFAULT_VS_INDEX_NAME,\
    OPENAI_EMBEDDING_MODELS,TOGETHER_EMBEDDING_MODELS,COHERE_EMBEDDING_MODELS
from model_discovery.configs.const import TARGET_SCALES, DEFAULT_CONTEXT_LENGTH,DEFAULT_TOKEN_MULTS,\
    DEFAULT_TRAINING_DATA,DEFAULT_EVAL_TASKS,DEFAULT_TOKENIZER,DEFAULT_OPTIM,DEFAULT_WANDB_PROJECT,\
        DEFAULT_WANDB_ENTITY,DEFAULT_RANDOM_SEED,DEFAULT_SAVE_STEPS,DEFAULT_LOG_STEPS





def apply_config(evosys,config):
    if st.session_state.is_demo:
        st.toast("***Demo mode:** No real config will be applied*")
        return
    if config['params']['evoname']!=evosys.params['evoname']:
        evosys.switch_ckpt(config['params']['evoname'],load_params=False)
    evosys.reconfig(design_cfg=config['design_cfg'],select_cfg=config['select_cfg'],search_cfg=config['search_cfg'])
    evosys.reload(config['params'])
    U.save_json(config,U.pjoin(evosys.evo_dir,'config.json'))
    st.toast(f"Applied and saved config in {evosys.evo_dir}")
    # st.rerun()


def apply_env_vars(evosys,env_vars):
    if st.session_state.is_demo:
        st.toast("***Demo mode:** No real config will be applied*")
        return
    changed=False
    for k,v in env_vars.items():
        if v:
            if k in os.environ and os.environ[k]==v:
                continue
            st.toast(f"Applied change to environment variable {k}")
            os.environ[k]=v
            changed=True
    if changed:
        st.toast("Reloading...") # neede to manually reload the evosys
    else:
        st.toast("No changes to environment variables")

    return changed

def apply_select_config(evosys,select_cfg):
    if st.session_state.is_demo:
        st.toast("***Demo mode:** No real config will be applied*")
        return
    total_n_seeds_dist = sum(select_cfg['n_seeds_dist'].values())
    if total_n_seeds_dist > 0:
        for k in select_cfg['n_seeds_dist']:
            if select_cfg['n_seeds_dist'][k] < 0:
                st.toast(f"The weight of the seed {k} is negative, failed to apply select config.")
                return
        select_cfg['n_seeds_dist'] = {k:v/total_n_seeds_dist for k,v in select_cfg['n_seeds_dist'].items()}
        with st.spinner('Applying and saving select config...'):
            evosys.reconfig(select_cfg=select_cfg)
            st.toast("Applied and saved select config")
            st.rerun()
    else:
        st.toast("The sum of the weights of the seeds distribution is 0, failed to apply select config.")

def apply_design_config(evosys,design_cfg):
    if st.session_state.is_demo:
        st.toast("***Demo mode:** No real config will be applied*")
        return
    with st.spinner('Applying and saving design config...'):
        evosys.reconfig(design_cfg=design_cfg)
        st.toast("Applied and saved design config")
        st.rerun()
def apply_search_config(evosys,search_cfg):
    if st.session_state.is_demo:
        st.toast("***Demo mode:** No real config will be applied*")
        return
    with st.spinner('Applying and saving search config...'):    
        evosys.reconfig(search_cfg=search_cfg)
        st.toast("Applied and saved search config")
        st.rerun()

def apply_ve_config(evosys,ve_cfg):
    if st.session_state.is_demo:
        st.toast("***Demo mode:** No real config will be applied*")
        return
    with st.spinner('Applying and saving ve config...'):    
        evosys.reconfig(ve_cfg=ve_cfg)
        st.toast("Applied and saved ve config")
        st.rerun()

def evosys_settings(evosys):
    st.subheader("Evolution System Settings")
    evosys_config(evosys)
    ve_config(evosys)


def evosys_config(evosys):
    with st.expander("Evolution Settings",expanded=False,icon='🧬'):
        config=U.load_json(U.pjoin(evosys.evo_dir,'config.json'))
        col1,col2=st.columns(2)
        with col1:
            with st.form("Evolution System Config"):
                _params=copy.deepcopy(evosys.params)
                _params['evoname']=st.text_input('Experiment Namespace',value=evosys.params['evoname'],
                    help='Changing this will create a new experiment namespace.')
                
                subcol1, subcol2, subcol3 = st.columns([1,1,0.3])
                with subcol1:
                    target_scale=st.select_slider('Target Scale',options=TARGET_SCALES,value=evosys.params['scales'].split(',')[-1],
                        help='The largest scale to train, will train `N Target` models at this scale.',
                        disabled=evosys.benchmark_mode or st.session_state.is_demo)
                    scales=[]
                    for s in TARGET_SCALES:
                        if int(target_scale.replace('M',''))>=int(s.replace('M','')):
                            scales.append(s)
                    _params['scales']=','.join(scales)
                with subcol2:
                    _params['selection_ratio']=st.slider('Selection Ratio',min_value=0.0,max_value=1.0,value=evosys.params['selection_ratio'],disabled=evosys.benchmark_mode,
                        help='The ratio of designs to keep from lower scale, e.g. targets 8 models on 70M with selection ratio 0.5 will train 16 models on 35M, 32 models on 14M.')
                with subcol3:
                    _params['n_target']=st.number_input('N Target',value=evosys.params['n_target'],min_value=1,step=1,
                        disabled=evosys.benchmark_mode or st.session_state.is_demo)
                

                _verify_budget = evosys.get_verify_budget(full=True)
                _params_manual_set_budget=True
                if _verify_budget == {}:
                    _params_manual_set_budget=False
                    _verify_budget={i:0 for i in TARGET_SCALES}
                    budget=_params['n_target']
                    for scale in _params['scales'].split(',')[::-1]:
                        _verify_budget[scale]=int(np.ceil(budget))
                        budget/=_params['selection_ratio']
                _manual_set_budget=st.checkbox('Use fine-grained verify budget below *(will over write the above)*',value=_params_manual_set_budget,
                    disabled=evosys.benchmark_mode or st.session_state.is_demo)
                sorted_keys = sorted(list(_verify_budget.keys()),key=lambda x: int(x.replace('M','')))
                _verify_budget = {k: _verify_budget[k] for k in sorted_keys}
                _verify_budget_df = pd.DataFrame(_verify_budget,index=['#'])
                _verify_budget_df = st.data_editor(_verify_budget_df,hide_index=True,disabled=evosys.benchmark_mode or st.session_state.is_demo)
                _verify_budget=_verify_budget_df.to_dict(orient='records')[0]
                _verify_budget={k:v for k,v in _verify_budget.items() if v!=0}
                if _manual_set_budget:
                    _params['verify_budget']=_verify_budget
                else:
                    _params['verify_budget']={}

                subcol1, subcol2, subcol3 = st.columns([1.2,2,2])
                with subcol1:
                    _params['max_samples']=st.number_input('Max Samples',value=evosys.params.get('max_samples',0),min_value=0,step=1,
                        disabled=evosys.benchmark_mode or st.session_state.is_demo,
                        help='Design-bound by the number of designs in the population to generate in total. 0 means no limit.')
                with subcol2:
                    _params['design_budget']=st.number_input('Design Budget ($)',value=evosys.params['design_budget'],min_value=0,step=100,
                        disabled=evosys.benchmark_mode or st.session_state.is_demo,
                        help='The total budget for running model design agents, 0 means no budget limit.')
                with subcol3:
                    bound_type=st.selectbox('Budget Type',options=BUDGET_TYPES,index=BUDGET_TYPES.index(evosys.params['budget_type']),
                        disabled=evosys.benchmark_mode or st.session_state.is_demo,
                        help=(
                            '**Design bound:** terminate the evolution after the design budget is used up, and will automatically promote verify budget; \n\n'
                            '**Verify bound:** terminate the evolution after the verify budget is used up, and will automatically promote design budget.\n\n'
                            'Design bound is recommended if you are using inference APIs (e.g. Anthropic, OpenAI, Together).'
                        ))
                    _params['budget_type']=bound_type
                
                _col1, _col2, _col3 = st.columns([1,1,1.2])
                with _col1:
                    _params['group_id']=st.text_input('Network Group ID',value=evosys.params['group_id'],
                        help='Used for the master node to find its nodes. Change it only if you wish to run multiple evolutions on multiple networks.')
                with _col2:
                    _params['challenging_threshold']=st.number_input('Max Impl. Retries',value=evosys.params['challenging_threshold'],min_value=0,step=1,
                        help='The number of failed *implementation retries* before a design is considered too challenging to give up.')
                with _col3:
                    _params['scale_stair_start']=st.select_slider('Ladder Start Scale',options=TARGET_SCALES,value=evosys.params['scale_stair_start'],disabled=evosys.benchmark_mode,
                        help='The scale to start the ladder training from.')
                

                cols = st.columns([1,1.4,1.3])
      
                with cols[1]:
                    _params['benchmark_mode'] = st.checkbox('Benchmark Mode',value=evosys.benchmark_mode,
                        disabled=st.session_state.evo_running or st.session_state.is_demo,
                        help='Whether it is an agent benchmark experiment. If checked, you can ignore most of the settings above.')
                
                with cols[2]:
                    _params['use_remote_db']=st.checkbox('Use Remote DB',value=evosys.params['use_remote_db'], disabled=True)

                with cols[0]:
                    apply_btn = st.form_submit_button("Apply and Save",disabled=st.session_state.evo_running or st.session_state.is_demo)

                if apply_btn:
                    with st.spinner("Applying and saving..."):
                        if _params['evoname']=='design_bound' and _params['design_budget']==0:
                            st.warning("You give inifinity budget to a design-bound evolution. The evolution will not terminate automatically.")
                        config['params']=_params
                        if config['params']['evoname']!=evosys.params['evoname']:
                            evosys.switch_ckpt(config['params']['evoname'],load_params=False)
                        evosys.reload(config['params'])
                        evosys.save_config()
                        st.toast(f"Applied and saved params in {evosys.evo_dir}.")
                        st.rerun()
        with col2:
            with st.form(f"Experiment Status"):
                st.write(f"Current Status for ```{evosys.evoname}```:")
                settings={}
                # settings['Experiment Directory']=evosys.evo_dir
                if evosys.design_budget_limit>0:
                    settings['Design Budget Usage']=f'{evosys.ptree.design_cost:.2f}/{evosys.design_budget_limit:.2f}'
                else:
                    settings['Design Budget Usage']=f'{evosys.ptree.design_cost:.2f}/♾️'
                settings['Verification Budge Usage']={}
                for scale,num in evosys.get_verify_budget(full=True).items():
                    remaining = evosys.selector.verify_budget.get(scale,0) 
                    settings['Verification Budge Usage'][scale]=f'{num-remaining}/{num}'
                sorted_keys = sorted(list(settings['Verification Budge Usage'].keys()),key=lambda x: U.letternum2num(x))
                settings['Verification Budge Usage'] = {k: settings['Verification Budge Usage'][k] for k in sorted_keys}
                settings['Budget Type']=evosys.params['budget_type']
                settings['Max Implementation Retries']=evosys.ptree.challenging_threshold
                n_sampled = len(os.listdir(U.pjoin(evosys.evo_dir,'db','designs')))
                max_samples = evosys.params['max_samples'] if evosys.params.get('max_samples',0)>0 else '♾️'
                settings['Max Samples']=f'{n_sampled}/{max_samples}'
                settings['Use Remote DB']=evosys.params['use_remote_db']
                if evosys.CM:
                    settings['Network Group ID']=evosys.CM.group_id
                # settings['Benchmark Mode']=evosys.benchmark_mode
                st.write(settings)
                st.form_submit_button("Refresh", disabled=st.session_state.is_demo)

        # with st.form("Benchmark Settings"):
        #     if not evosys.benchmark_mode:
        #         st.caption(f'Benchmark Settings (`{evosys.evoname}` is not in benchmark mode)')
        #     else:
        #         st.caption('Benchmark Settings')
        #     cols = st.columns([0.8,1,2,1.2,0.8])
        #     with cols[0]:
        #         _n_trials = st.number_input('Number of Trials',min_value=1,value=100,disabled=st.session_state.evo_running or not evosys.benchmark_mode,
        #             help='The number of design sessions to run.')
        #     with cols[1]:
        #         _MODE_OPTIONS = BENCH_MODE_OPTIONS.copy()
        #         _MODE_OPTIONS[3] = 'Mixed (Use right or select config)'
        #         _design_mode = st.selectbox('Design Mode',options=_MODE_OPTIONS,index=0,disabled=st.session_state.evo_running or not evosys.benchmark_mode,
        #             help='If you choose Mixed mode, the number of seeds will follow the distribution settings, otherwise, it will always sample 1 (Mutation-only), 2 (Crossover-only), 0 (Scratch-only) seeds respectively.'
        #         )
        #         if _design_mode == 'Mixed (Use right or select config)':
        #             _design_mode = 'Mixed'
        #     with cols[2]:
        #         default_n_seeds_dist = {
        #             '0': 0.1,
        #             '1': 0.8,
        #             '2': 0.1,
        #             '3': 0,
        #             '4': 0,
        #             '5': 0,
        #         }
        #         _n_seeds_dist_df = pd.DataFrame(default_n_seeds_dist,index=['Weights'])
        #         _n_seeds_dist_df = st.data_editor(_n_seeds_dist_df,use_container_width=True,disabled=st.session_state.evo_running or not evosys.benchmark_mode)
        #         _n_seeds_dist = _n_seeds_dist_df.to_dict(orient='records')[0]
        #         _n_seeds_dist = {k:v for k,v in _n_seeds_dist.items()}
        #     with cols[3]:
        #         _allow_tree=st.checkbox("Allow Sampling Tree",value=True,disabled=st.session_state.evo_running or not evosys.benchmark_mode,
        #             help='Whether allow sampling from the phylogenetic tree or only sampling from the seed references.'
        #         )
        #         _overwrite_config = st.checkbox('Overwrite Mixed Cfg.',value=True,disabled=st.session_state.evo_running or not evosys.benchmark_mode,
        #             help='If checked, will apply the n seeds distribution on the left instead of the one in config in Mixed mode. Notice that if use this one, there will be no warmup.')
                
        #     benchmark_settings = {
        #         'n_trials': _n_trials,
        #         'max_retries': None,
        #         'design_mode': _design_mode,
        #         'n_seeds_dist': _n_seeds_dist,
        #         'overwrite_config': _overwrite_config,
        #         'allow_tree': _allow_tree,
        #     }

        #     with cols[4]:
        #         st.write('')
        #         apply_btn = st.form_submit_button("Apply and Save",disabled=st.session_state.evo_running or not evosys.benchmark_mode)
            
        #     if apply_btn:
        #         with st.spinner("Applying and saving..."):
        #             evosys.reconfig(benchmark_settings=benchmark_settings)
        #             st.toast("Applied and saved benchmark config")
        #             st.rerun()

def ve_config(evosys):
    with st.expander(f"Verification Engine Settings for ```{evosys.evoname}```",expanded=False,icon='⚙️'):
        with st.form("Verification Engine Config"):
            _ve_cfg=copy.deepcopy(evosys.ve_cfg)
            
            cols = st.columns([1,1,1,1,1])
            with cols[0]:
                _ve_cfg['seed'] = st.number_input('Random Seed',min_value=0,value=_ve_cfg.get('seed',DEFAULT_RANDOM_SEED))
            with cols[1]:
                _ve_cfg['save_steps'] = st.number_input('Save Steps',min_value=0,value=_ve_cfg.get('save_steps',DEFAULT_SAVE_STEPS))
            with cols[2]:
                _ve_cfg['logging_steps'] = st.number_input('Logging Steps',min_value=0,value=_ve_cfg.get('logging_steps',DEFAULT_LOG_STEPS))
            with cols[3]:
                _ve_cfg['wandb_project'] = st.text_input('Weights & Biases Project',value=_ve_cfg.get('wandb_project',DEFAULT_WANDB_PROJECT))
            with cols[4]:
                _ve_cfg['wandb_entity'] = st.text_input('Weights & Biases Entity',value=_ve_cfg.get('wandb_entity',DEFAULT_WANDB_ENTITY))

            cols=st.columns([4,1.55,1,1])
            with cols[0]:
                training_token_multipliers = _ve_cfg.get('training_token_multipliers',DEFAULT_TOKEN_MULTS)
                sorted_keys = sorted(training_token_multipliers.keys(),key=lambda x: int(x.replace('M','')))
                training_token_multipliers = {k:training_token_multipliers[k] for k in sorted_keys}
                training_token_multipliers_df = pd.DataFrame(training_token_multipliers,index=['mult'])
                training_token_multipliers_df = st.data_editor(training_token_multipliers_df,use_container_width=True)
                training_token_multipliers = training_token_multipliers_df.to_dict(orient='records')[0]
                _ve_cfg['training_token_multipliers']=training_token_multipliers
                # _ve_cfg['training_token_multiplier']=st.number_input('Training Token Multiplier',min_value=0,value=_ve_cfg.get('training_token_multipliers',DEFAULT_TOKEN_MULTS))
            with cols[1]:
                _ve_cfg['tokenizer'] = st.text_input('Tokenizer',value=_ve_cfg.get('tokenizer',DEFAULT_TOKENIZER))
            with cols[2]:
                _ve_cfg['context_length'] = st.number_input('Context Length',min_value=0,value=int(_ve_cfg.get('context_length',DEFAULT_CONTEXT_LENGTH)))
            with cols[3]:
                _ve_cfg['optim'] = st.text_input('Optimizer',value=_ve_cfg.get('optim',DEFAULT_OPTIM))
            
            _ve_cfg['eval_tasks'] = st.text_input('Evaluation Tasks (comma seperated, refer to https://github.com/EleutherAI/lm-evaluation-harness/tree/main/lm_eval/tasks for most available tasks)',value=_ve_cfg.get('eval_tasks',','.join(DEFAULT_EVAL_TASKS)))
            _ve_cfg['training_data'] = st.text_input('Training Data (comma seperated, processed ones or datasets from hugginface hub, see help ❓ on the right)',value=_ve_cfg.get('training_data',','.join(DEFAULT_TRAINING_DATA)),
                help=(
                    'If are inputting a huggingface dataset, it must have `train` split and `text` column, '
                    'e.g. https://huggingface.co/datasets/allenai/c4, '
                    'you can input the dataset path and optionally the subset (if there are subsets in the path), '
                    'use : as separator, e.g. `allenai/c4:en`'
                )
            )
            
            _ve_cfg['context_length'] = str(_ve_cfg['context_length'])

            st.form_submit_button("Save and Apply",
                on_click=apply_ve_config,args=(evosys,_ve_cfg),
                # disabled=st.session_state.evo_running,
                disabled=st.session_state.is_demo,
                help='Before a design thread is started, the agent type of each role will be randomly selected based on the weights.'
            )   



AGENT_TYPE_LABELS = {
    'DESIGN_PROPOSER':'Proposal Agent',
    'PROPOSAL_REVIEWER':'Proposal Reviewer',
    'IMPLEMENTATION_PLANNER':'Impl. Planner',
    'IMPLEMENTATION_CODER':'Implementation Coder',
    'IMPLEMENTATION_OBSERVER':'Impl. Observer',
    'SEARCH_ASSISTANT': '*Sep. Search Assistant*'
}

def model_design_engine_settings(evosys):
    st.subheader("Model Design Engine Settings")
    select_config(evosys)
    search_config(evosys)
    design_config(evosys)


def select_config(evosys):
    select_cfg=copy.deepcopy(evosys.select_cfg)
    
    select_method=select_cfg.get('select_method',DEFAULT_SELECT_METHOD)
    verify_strategy=select_cfg.get('verify_strategy',DEFAULT_VERIFY_STRATEGY)
    n_sources=select_cfg.get('n_sources',DEFAULT_N_SOURCES)
    seed_dist=select_cfg.get('seed_dist',DEFAULT_SEED_DIST)
    n_seeds_settings=select_cfg.get('n_seeds',DEFAULT_N_SEEDS_SETTINGS)
    n_seeds_dist=select_cfg.get('n_seeds_dist',DEFAULT_N_SEEDS_DIST)
    random_allow_tree=select_cfg.get('random_allow_tree',DEFAULT_RANDOM_ALLOW_TREE)

    with st.expander(f"Seed Selector Configurations for ```{evosys.evoname}```",expanded=False,icon='🌱'):
        with st.form("Seed Selector Config"):
            _col1,_col2=st.columns([2,3])
            with _col1:
                st.write('###### Configure Selector')
                cols=st.columns(2)
                with cols[0]:
                    select_method=DEFAULT_SELECT_METHOD if select_method not in SELECT_METHODS else select_method
                    select_cfg['select_method']=st.selectbox('Select Method',options=SELECT_METHODS,index=SELECT_METHODS.index(select_method))
                with cols[1]:
                    verify_strategy=DEFAULT_VERIFY_STRATEGY if verify_strategy not in VERIFY_STRATEGIES else verify_strategy
                    select_cfg['verify_strategy']=st.selectbox('Verify Strategy',options=VERIFY_STRATEGIES,index=VERIFY_STRATEGIES.index(verify_strategy))
            with _col2:
                st.write('###### Configure *Seed* Selection Distribution (non-random)')
                cols = st.columns(3)
                with cols[0]:
                    seed_dist['scheduler'] = st.selectbox('Scheduler',options=SCHEDULER_OPTIONS,index=SCHEDULER_OPTIONS.index(seed_dist['scheduler']))
                with cols[1]:
                    seed_dist['restart_prob'] = st.slider('Restart Probability',min_value=0.0,max_value=1.0,step=0.01,value=DEFAULT_SEED_DIST['restart_prob'])
                with cols[2]:
                    seed_dist['warmup_rounds'] = st.number_input('Warmup (Restart)',min_value=0,value=seed_dist['warmup_rounds'],
                        help="Number of verified designs are produced. In warmup rounds, at least one seed will be selected from the initial seeds. After warmup, the probability of selecting from initial seeds is determined by restart scheduler.")
            
            if st.session_state.use_cache:
                sources={i:len(st.session_state.filter_by_types[i]) for i in DEFAULT_N_SOURCES}
            else:
                sources={i:len(evosys.ptree.filter_by_type(i)) for i in DEFAULT_N_SOURCES}
        
            Col1,Col2 = st.columns([4.5,1.1])
            with Col1:
                st.markdown("###### Configure the number of *references* from each source")
                cols = st.columns(len(sources))
                count = 0
                for i,source in enumerate(sources):
                    # if source =='ReferenceCore': 
                    #     n_sources[source] = 0
                    #     continue
                    with cols[count]:
                        count += 1
                        if source in ['DesignArtifact','DesignArtifactImplemented']:
                            if source == 'DesignArtifactImplemented':
                                label = 'DesignArtImpl.'
                            else:
                                label = 'DesignArtifact'
                            n_sources[source] = st.number_input(label=label,min_value=0,value=n_sources[source],
                                disabled=st.session_state.is_demo)
                        else:
                            if source == 'ReferenceCoreWithTree':
                                label = 'RefCoreWithTree'
                            elif source == 'ReferenceWithCode':
                                label = 'RefWithCode'
                            else:
                                label = source
                            n_sources[source] = st.number_input(label=f'{label} ({sources[source]})',min_value=0,value=n_sources[source],max_value=sources[source],
                                disabled=st.session_state.is_demo)
                select_cfg['n_sources']=n_sources
                select_cfg['seed_dist']=seed_dist
            with Col2:
                st.write('###### Other Settings')
                # st.write('')
                # st.write('')
                select_cfg['random_allow_tree']=st.checkbox('Random Allow Tree',value=random_allow_tree,
                    help='If true, will allow the random selector to select from evo tree nodes.',
                    disabled=st.session_state.is_demo)
                select_cfg['verify_all']=st.checkbox('Verify All Designs',value=select_cfg.get('verify_all',False),
                    help='If true, will verify all designs at the lowest scale.',
                    disabled=st.session_state.is_demo)


            Col1,Col2 = st.columns([5,2.8])
            with Col1:
                st.markdown('###### Configure the Number of Seeds Distribution')
                cols=st.columns([1,1,2.7])
                with cols[0]:
                    n_seeds_settings['warmup_rounds_crossover']=st.number_input('Warmup (Crossover)',min_value=0,value=n_seeds_settings['warmup_rounds_crossover'],
                        disabled=st.session_state.is_demo)
                with cols[1]:
                    n_seeds_settings['warmup_rounds_scratch']=st.number_input('Warmup (Scratch)',min_value=0,value=n_seeds_settings['warmup_rounds_scratch'],
                        disabled=st.session_state.is_demo)
                with cols[2]:
                    n_seeds_dist = U.sort_dict_by_scale(n_seeds_dist)
                    n_seeds_dist_df = pd.DataFrame(n_seeds_dist,index=['p (%)'])
                    n_seeds_dist_df = st.data_editor(n_seeds_dist_df*100,use_container_width=True,disabled=st.session_state.is_demo)
                    n_seeds_dist = n_seeds_dist_df.to_dict(orient='records')[0]
                    n_seeds_dist = {k:v/100 for k,v in n_seeds_dist.items()}
                select_cfg['n_seeds_dist']=n_seeds_dist
                select_cfg['n_seeds_settings']=n_seeds_settings
            with Col2:
                st.markdown('###### Distribution of Seed Designs (%)')
                if st.session_state.use_cache:
                    seed_designs = st.session_state.filter_by_types['ReferenceCoreWithTree']
                else:
                    seed_designs = evosys.ptree.filter_by_type('ReferenceCoreWithTree')
                seed_design_dist = select_cfg.get('seed_design_dist',{})
                for seed_design in seed_designs:
                    seed_design_dist[seed_design] = seed_design_dist.get(seed_design,1/len(seed_designs))
                seed_design_dist_df = pd.DataFrame(seed_design_dist,index=['Weights'])
                seed_design_dist_df = st.data_editor(seed_design_dist_df*100,hide_index=True,use_container_width=True,disabled=st.session_state.is_demo)
                seed_design_dist = seed_design_dist_df.to_dict(orient='records')[0]
                seed_design_dist = {k:v/100 for k,v in seed_design_dist.items()}
                select_cfg['seed_design_dist'] = seed_design_dist

            st.form_submit_button("Save and Apply",
                on_click=apply_select_config,args=(evosys,select_cfg),
                # disabled=st.session_state.evo_running,
                disabled=st.session_state.is_demo,
            )   


def design_config(evosys):

    design_cfg=copy.deepcopy(evosys.design_cfg)

    design_cfg['max_attemps']=U.safe_get_cfg_dict(design_cfg,'max_attemps',DEFAULT_MAX_ATTEMPTS)
    design_cfg['agent_types']=U.safe_get_cfg_dict(design_cfg,'agent_types',DEFAULT_AGENTS)
    design_cfg['termination']=U.safe_get_cfg_dict(design_cfg,'termination',DEFAULT_TERMINATION)
    design_cfg['threshold']=U.safe_get_cfg_dict(design_cfg,'threshold',DEFAULT_THRESHOLD)
    design_cfg['search_settings']=U.safe_get_cfg_dict(design_cfg,'search_settings',DEFAULT_SEARCH_SETTINGS)
    design_cfg['running_mode']=RunningModes(design_cfg.get('running_mode',DEFAULT_MODE))
    design_cfg['num_samples']=U.safe_get_cfg_dict(design_cfg,'num_samples',DEFAULT_NUM_SAMPLES)
    design_cfg['unittest_pass_required']=design_cfg.get('unittest_pass_required',DEFAULT_UNITTEST_PASS_REQUIRED)
    design_cfg['crossover_no_ref']=design_cfg.get('crossover_no_ref',DEFAULT_CROSSOVER_NO_REF)
    design_cfg['mutation_no_tree']=design_cfg.get('mutation_no_tree',DEFAULT_MUTATION_NO_TREE)
    design_cfg['scratch_no_tree']=design_cfg.get('scratch_no_tree',DEFAULT_SCRATCH_NO_TREE)
    design_cfg['use_unlimited_prompt']=design_cfg.get('use_unlimited_prompt',DEFAULT_USE_UNLIMITED_PROMPT)
    design_cfg['flow_type']=design_cfg.get('flow_type','gau')
    design_cfg['no_f_checkers']=design_cfg.get('no_f_checkers',False)

    #### Configure design
    

    with st.expander(f"Design Agent Configurations for ```{evosys.evoname}```",expanded=False,icon='🎨'):
        with st.form("Design Agent Config"):
                # st.markdown("#### Configure the base models for each agent")
            agent_types = {}
            cols = st.columns(len(AGENT_TYPE_LABELS))
            for i,agent in enumerate(AGENT_TYPE_LABELS):
                with cols[i]:
                    index=0 
                    options=copy.deepcopy(AGENT_OPTIONS[agent])
                    help=None
                    if agent in ['SEARCH_ASSISTANT']:
                        index=len(options)-1
                        help='Whether use a separate search assistant agent to perform search tasks. (deprecated for now)'
                    elif agent in ['IMPLEMENTATION_PLANNER']:
                        options+=['None']
                    elif agent in ['IMPLEMENTATION_OBSERVER']:
                        index=len(options)-2
                    elif agent in ['IMPLEMENTATION_CODER']:
                        index=len(options)-1
                    options += ['hybrid']
                    index = options.index(design_cfg['agent_types'][agent]) if design_cfg['agent_types'][agent] in options else 0
                    agent_types[agent] = st.selectbox(label=AGENT_TYPE_LABELS[agent],options=options,index=index,
                        disabled=agent=='SEARCH_ASSISTANT' or st.session_state.is_demo,help=help)
            design_cfg['agent_types'] = agent_types
            st.caption('***Note:** If you choose "hybrid", you will need to configure the weights for each agent below in advanced configs later.*')

            col1,col2,col3=st.columns([3.2,1.8,1])
            termination={}
            threshold={}
            max_attempts = {}
            with col1:
                st.markdown("##### Configure termination and budgets")
                cols=st.columns(4)
                with cols[0]:
                    termination['max_failed_rounds'] = st.number_input(label="Max failed rounds",min_value=1,value=design_cfg['termination']['max_failed_rounds'],
                                                                       help='The maximum number of failed rounds before termination. 0 is no limit. ')
                with cols[1]:
                    termination['max_total_budget'] = st.number_input(label="Max total budget",min_value=0,value=design_cfg['termination']['max_total_budget'],
                                                                       help='The maximum number of design attempts before termination. 0 is no limit.')
                with cols[2]:
                    termination['max_debug_budget'] = st.number_input(label="Max debug budget",min_value=0,value=design_cfg['termination']['max_debug_budget'],
                                                                       help='The maximum number of debug attempts before termination. 0 is no limit.')
                with cols[3]:
                    max_attempts['max_search_rounds'] = st.number_input(label="Max search rounds",min_value=0,value=design_cfg['max_attemps']['max_search_rounds'],
                                                                       help='The maximum number of search attempts before termination. 0 is NO SEARCH.')
            with col2:
                st.markdown("##### Configure rating thresholds")
                cols=st.columns(2)
                with cols[0]:
                    threshold['proposal_rating'] = st.slider(label="Proposal rating",min_value=0.0,max_value=5.0,value=float(design_cfg['threshold']['proposal_rating']),step=0.5)
                with cols[1]:
                    threshold['implementation_rating'] = st.slider(label="Impl. observation",min_value=0.0,max_value=5.0,value=float(design_cfg['threshold']['implementation_rating']),step=0.5)
            design_cfg['termination'] = termination
            design_cfg['threshold'] = threshold 

            with col3:
                # st.markdown("###### Input Settings")
                design_cfg['crossover_no_ref'] = st.checkbox("Crossover no ref",value=design_cfg['crossover_no_ref'],
                    help='If true, will not use references in crossover mode, it is recommended as crossover does not need cold start, and context length can be over long.')
                design_cfg['mutation_no_tree'] = st.checkbox("Mutation no tree",value=design_cfg['mutation_no_tree'],
                    help='If true, will not show full tree but only the document for types with tree (i.e., ReferenceCoreWithTree, DesignArtifactImplemented) in mutation mode, it is recommended as context length can be over long.')
                design_cfg['scratch_no_tree'] = st.checkbox("Scratch no tree",value=design_cfg['scratch_no_tree'],
                    help='If true, will not show full tree but only the document for types with tree (i.e., ReferenceCoreWithTree, DesignArtifactImplemented) in scratch mode, it is recommended as context length can be over long.')
            


            col1,col2,col3=st.columns([5,5,2.5])
            with col1:
                st.markdown("##### Configure max number of attempts")
                cols=st.columns(3)
                with cols[0]:
                    max_attempts['design_proposal'] = st.number_input(label="Proposal attempts",min_value=3,value=design_cfg['max_attemps']['design_proposal'])
                with cols[1]:
                    max_attempts['implementation_debug'] = st.number_input(label="Debug attempts",min_value=3,value=design_cfg['max_attemps']['implementation_debug'])
                with cols[2]:
                    max_attempts['post_refinement'] = st.number_input(label="Post refinements",min_value=0,value=design_cfg['max_attemps']['post_refinement'])
            design_cfg['max_attemps'] = max_attempts
            with col2:
                num_samples={}
                st.markdown("##### Configure number of samples")
                cols=st.columns(3)
                with cols[0]:
                    num_samples['proposal']=st.number_input(label="Proposal Samples",min_value=1,value=design_cfg['num_samples']['proposal'])
                with cols[1]:
                    num_samples['implementation']=st.number_input(label="Impl. Samples",min_value=1,value=design_cfg['num_samples']['implementation'])
                with cols[2]:
                    rerank_methods=['random','rating']
                    num_samples['rerank_method']=st.selectbox(label="Rerank Method",options=rerank_methods,index=rerank_methods.index('rating'),
                    disabled=True)
            design_cfg['num_samples']=num_samples

            with col3:
                st.markdown("###### Other Configurations")
                design_cfg['unittest_pass_required']=st.checkbox('Unittests required',value=design_cfg['unittest_pass_required'],
                    help='If true, will require unittests to pass besides checkers and observers.')
                design_cfg['use_unlimited_prompt']=st.checkbox('Use unlimited prompt',value=design_cfg['use_unlimited_prompt'],
                    help='If true, will prompt the agent to not worry about the number of tokens in their reasoning and response, and use as many as needed to give the best response.')

            cols = st.columns([0.9,1,1,3.3])
            with cols[1]:
                if evosys.benchmark_mode:
                    _use_naive_flow=st.checkbox('*Use Naive Flow*',value=design_cfg['flow_type']=='naive',
                        disabled=not evosys.benchmark_mode or st.session_state.is_demo,
                        help='If true, will use the Naive GAB Coder and Observer instead of the GAUTree Coder and Observer. Only applicable in benchmark mode.')
                    design_cfg['flow_type']='naive' if _use_naive_flow else 'gau'
            with cols[2]:
                if evosys.benchmark_mode:
                    design_cfg['no_f_checkers']=st.checkbox('*No F-Checkers*',value=design_cfg['no_f_checkers'],
                        disabled=not evosys.benchmark_mode or st.session_state.is_demo,
                        help='If true, will turn off the Functional Checkers when checking the implementation code. Only applicable in benchmark mode.')

            with cols[0]:
                st.form_submit_button("Save and Apply",
                    on_click=apply_design_config,args=(evosys,design_cfg),
                    # disabled=st.session_state.evo_running,
                    disabled=st.session_state.is_demo,
                )   


EMBEDDING_MODELS = {
    'OpenAI':OPENAI_EMBEDDING_MODELS,
    'Cohere':COHERE_EMBEDDING_MODELS,
    'Together':TOGETHER_EMBEDDING_MODELS,
}

def search_config(evosys):

    with st.expander(f"Search Engine Configurations for ```{evosys.evoname}```",expanded=False,icon='🔎'):
        search_cfg=copy.deepcopy(evosys.agents.sss.cfg)
        
        with st.form("Search Engine Config"):

            COL1,COL2 = st.columns([10,6])
            with COL1:
                st.write("##### Internal Library Search Configurations (0 is disable)")
                cols=st.columns([2,2,2,3])
                with cols[0]:
                    search_cfg['result_limits']['lib']=st.number_input("Library Primary",value=search_cfg['result_limits']['lib'],min_value=0,step=1,
                        help='The core library with 300+ state-of-the-art language model architecture related papers.')
                with cols[1]:
                    search_cfg['result_limits']['lib2']=st.number_input("Library Secondary",value=0,min_value=0,step=1,
                        help='The secondary library of the papers that are cited by the primary library.')
                with cols[2]:
                    search_cfg['result_limits']['libp']=st.number_input("Library Plus",value=0,min_value=0,step=1,
                        help='The library of the papers that are recommended by Semantic Scholar for core library papers.')
                with cols[3]:
                    search_cfg['rerank_ratio']=st.slider("Rerank Scale Ratio (0 is disable)",min_value=0.0,max_value=1.0,value=search_cfg['rerank_ratio'],step=0.01)
                
            with COL2:
                st.write("##### Vector Store Embeddings")
                _vectorstore_embeddings=search_cfg['embedding_models']['vectorstore']
                cols=st.columns([1,1.3])
                with cols[0]:
                    if _vectorstore_embeddings in EMBEDDING_MODELS['OpenAI']:
                        embedding_model_type = 'OpenAI'
                    elif _vectorstore_embeddings in EMBEDDING_MODELS['Cohere']:
                        embedding_model_type = 'Cohere'
                    elif _vectorstore_embeddings in EMBEDDING_MODELS['Together']:
                        embedding_model_type = 'Together'
                    _model_types = list(EMBEDDING_MODELS.keys())
                    embedding_model_type = st.selectbox("Embedding Model Type",key='vectorstore_embedding_model_type',
                        options=_model_types,index=_model_types.index(embedding_model_type),disabled=True)
                with cols[1]:
                    _index=EMBEDDING_MODELS[embedding_model_type].index(_vectorstore_embeddings) if _vectorstore_embeddings in EMBEDDING_MODELS[embedding_model_type] else 0
                    _vectorstore_embeddings=st.selectbox("Embedding Model",key='vectorstore_embedding_model',
                        options=EMBEDDING_MODELS[embedding_model_type],index=_index,disabled=True)
            search_cfg['embedding_models']['vectorstore'] = _vectorstore_embeddings
            

            COL1,COL2 = st.columns([11,3])
            with COL1:
                st.write("##### External Search Configurations")
                cols=st.columns([2,2,2,2,2])
                with cols[0]:
                    search_cfg['result_limits']['s2']=st.number_input("S2 Result Limit",value=search_cfg['result_limits']['s2'],min_value=0,step=1)
                with cols[1]:
                    search_cfg['result_limits']['arxiv']=st.number_input("Arxiv Result Limit",value=search_cfg['result_limits']['arxiv'],min_value=0,step=1)
                with cols[2]:
                    search_cfg['result_limits']['pwc']=st.number_input("PwC Result Limit",value=search_cfg['result_limits']['pwc'],min_value=0,step=1)
                with cols[3]:
                    _options=['none','small','large','huge']
                    _index=_options.index(search_cfg['perplexity_settings']['model_size']) if search_cfg['perplexity_settings']['model_size'] in _options else 3
                    search_cfg['perplexity_settings']['model_size']=st.selectbox("Perplexity Model Size",options=_options,index=_index)
                with cols[4]:
                    search_cfg['perplexity_settings']['max_tokens']=st.number_input("Perplexity Max Tokens",value=search_cfg['perplexity_settings']['max_tokens'],min_value=500,step=100,disabled=search_cfg['perplexity_settings']['model_size']=='none')
            
                st.write("##### Proposal Search Configurations")
                _proposal_search_cfg=search_cfg['proposal_search']
                _proposal_embedding_model=search_cfg['embedding_models']['proposal']
                _proposal_embedding_distance=search_cfg['embedding_distances']['proposal']

            with COL2:
                st.write("##### Vector Store Index")
                search_cfg['index_name']=st.text_input("Index Name",value=search_cfg['index_name'],disabled=True)
              

            cols = st.columns([1,1,1.5,1,1.3,1])
            with cols[0]:
                _proposal_search_cfg['top_k']=st.number_input("Top K",value=_proposal_search_cfg['top_k'],min_value=0,step=1)
            with cols[1]:
                _proposal_search_cfg['sibling']=st.number_input("Sibling Top K",value=_proposal_search_cfg['sibling'],min_value=0,step=1)
            with cols[2]:
                _proposal_search_cfg['cutoff']=st.slider("Cutoff",min_value=0.0,max_value=1.0,value=_proposal_search_cfg['cutoff'],step=0.01)
            with cols[3]:
                if _proposal_embedding_model in EMBEDDING_MODELS['OpenAI']:
                    embedding_model_type = 'OpenAI'
                elif _proposal_embedding_model in EMBEDDING_MODELS['Cohere']:
                    embedding_model_type = 'Cohere'
                elif _proposal_embedding_model in EMBEDDING_MODELS['Together']:
                    embedding_model_type = 'Together'
                _model_types = list(EMBEDDING_MODELS.keys())
                embedding_model_type = st.selectbox("Embedding Model Type",options=_model_types,index=_model_types.index(embedding_model_type))
            with cols[4]:
                _index=EMBEDDING_MODELS[embedding_model_type].index(_proposal_embedding_model) if _proposal_embedding_model in EMBEDDING_MODELS[embedding_model_type] else 0
                _proposal_embedding_model=st.selectbox("Embedding Model",options=EMBEDDING_MODELS[embedding_model_type],index=_index)
            with cols[5]:
                embedding_distances = [i.value for i in EmbeddingDistance]
                _proposal_embedding_distance=st.selectbox("Embedding Distance",options=embedding_distances,index=embedding_distances.index(_proposal_embedding_distance))

            search_cfg['proposal_search'] = _proposal_search_cfg
            search_cfg['embedding_models']['proposal'] = _proposal_embedding_model
            search_cfg['embedding_distances']['proposal'] = _proposal_embedding_distance

            _unit_search_cfg = search_cfg['unit_search']
            _unit_embedding_model = search_cfg['embedding_models']['unitcode']
            _unit_embedding_distance = search_cfg['embedding_distances']['unitcode']

            st.write("##### Unit Code Search Configurations")
            cols = st.columns([1,1.5,1,1.5,1])
            with cols[0]:
                _unit_search_cfg['top_k']=st.number_input("Top K",value=_unit_search_cfg['top_k'],min_value=0,step=1)
            with cols[1]:
                _unit_search_cfg['cutoff']=st.slider("Cutoff",key='unit_cutoff',
                    min_value=0.0,max_value=1.0,value=_unit_search_cfg['cutoff'],step=0.01)
            with cols[2]:
                if _unit_embedding_model in EMBEDDING_MODELS['OpenAI']:
                    embedding_model_type = 'OpenAI'
                elif _unit_embedding_model in EMBEDDING_MODELS['Cohere']:
                    embedding_model_type = 'Cohere'
                elif _unit_embedding_model in EMBEDDING_MODELS['Together']:
                    embedding_model_type = 'Together'
                _model_types = list(EMBEDDING_MODELS.keys())
                embedding_model_type = st.selectbox("Embedding Model Type",key='unit_embedding_model_type',
                    options=_model_types,index=_model_types.index(embedding_model_type))
            with cols[3]:
                _index=EMBEDDING_MODELS[embedding_model_type].index(_unit_embedding_model) if _unit_embedding_model in EMBEDDING_MODELS[embedding_model_type] else 0
                _unit_embedding_model=st.selectbox("Embedding Model",key='unit_embedding_model',
                    options=EMBEDDING_MODELS[embedding_model_type],index=_index)
            with cols[4]:
                embedding_distances = [i.value for i in EmbeddingDistance]
                _unit_embedding_distance=st.selectbox("Embedding Distance",key='unit_embedding_distance',
                    options=embedding_distances,index=embedding_distances.index(_unit_embedding_distance))
            search_cfg['unit_search'] = _unit_search_cfg
            search_cfg['embedding_models']['unitcode'] = _unit_embedding_model
            search_cfg['embedding_distances']['unitcode'] = _unit_embedding_distance

            st.form_submit_button("Save and Apply",
                on_click=apply_search_config,args=(evosys,search_cfg),
                # disabled=st.session_state.evo_running,
                disabled=st.session_state.is_demo,
            )


def delete_exp_from_db(evosys,exp):
    collection=evosys.ptree.remote_db.collection('experiments')
    collection.document(exp).delete()
    st.toast(f"Deleted experiment from remote DB: {exp}")

def sync_exps_to_db(evosys):
    for exp in os.listdir(evosys.ckpt_dir):
        config=U.load_json(U.pjoin(evosys.ckpt_dir,exp,'config.json'))
        evosys.ptree.FM.upload_experiment(exp,config)
    st.toast("Synced all experiments to remote DB")


def download_exp_from_db(evosys,exp):
    evosys.ptree.FM.download_experiment(evosys.ckpt_dir,exp)

def sync_exps_from_db(evosys):
    collection=evosys.ptree.remote_db.collection('experiments')
    docs=collection.get()
    for doc in docs:
        doc_id=doc.id
        doc=doc.to_dict()
        config=doc.get('config',{})
        U.mkdir(U.pjoin(evosys.ckpt_dir,doc_id))
        U.mkdir(U.pjoin(evosys.ckpt_dir,doc_id,'ve'))
        U.mkdir(U.pjoin(evosys.ckpt_dir,doc_id,'db','sessions'))
        U.mkdir(U.pjoin(evosys.ckpt_dir,doc_id,'db','designs'))
        if config:
            U.save_json(config,U.pjoin(evosys.ckpt_dir,doc_id,'config.json'))
    st.toast("Synced all experiments from remote DB")
    st.rerun()


def advanced_configs(evosys):
    st.write("#### *Advanced Configurations*")
    hybrid_agent_weights(evosys)
    selector_ranking_exploration_config(evosys)

def hybrid_agent_weights(evosys):
    design_cfg=copy.deepcopy(evosys.design_cfg)
    design_cfg['agent_weights']=U.safe_get_cfg_dict(design_cfg,'agent_weights',DEFAULT_AGENT_WEIGHTS)
    with st.expander(f"Hybrid Agent Weights for ```{evosys.evoname}```",expanded=False,icon='🤖'):
        cols=st.columns(5)
        for i in range(5):
            agent_type = list(AGENT_TYPE_LABELS.keys())[i]
            with cols[i]:
                st.write(f'###### {AGENT_TYPE_LABELS[agent_type]}')
                for idx,option in enumerate(AGENT_OPTIONS[agent_type]):
                    cur_weight=float(design_cfg['agent_weights'][agent_type][idx])
                    design_cfg["agent_weights"][agent_type][idx]=st.number_input(option,min_value=0.0,max_value=1.0,value=cur_weight,step=0.05,
                            key=f'agent_weight_{agent_type}_{idx}')
                remaining_weight=round(1.0-sum(design_cfg['agent_weights'][agent_type]),2)
                if remaining_weight==0:
                    st.success(f'Remaining weight: ```{remaining_weight:.2f}```')
                elif remaining_weight>0:
                    st.warning(f'Remaining weight: ```{remaining_weight:.2f}```')
                else:
                    st.error(f'Weights exceeded: ```{remaining_weight:.2f}```')
        st.button("Save and Apply",key='save_agent_weights',
            on_click=apply_design_config,args=(evosys,design_cfg),
            # disabled=st.session_state.evo_running,
            disabled=st.session_state.is_demo,
            help='Before a design thread is started, the agent type of each role will be randomly selected based on the weights.'
        )   
        
def selector_ranking_exploration_config(evosys):
    with st.expander(f"Selector Ranking and Exploration Settings for ```{evosys.evoname}```",expanded=False,icon='🧰'):
        select_cfg=copy.deepcopy(evosys.select_cfg)

        with st.form("Selector Ranking and Exploration Settings"):
            ranking_args = U.safe_get_cfg_dict(select_cfg,'ranking_args',DEFAULT_RANKING_ARGS)
            cols = st.columns([5,1,0.8,0.8])
            with cols[0]:
                _cols=st.columns([2,1])
                with _cols[0]:
                    _value = ranking_args['ranking_method']
                    if isinstance(_value,str):
                        _value = [_value]
                    ranking_args['ranking_method'] = st.multiselect('Ranking method (Required)',options=RANKING_METHODS,default=_value,
                        help='Ranking method to use, if muliple methods are provided, will be aggregated by the "multi-rank merge" method')
                with _cols[1]:
                    ranking_args['multi_rank_merge'] = st.selectbox('Multi-rank merge',options=MERGE_METHODS)
            with cols[1]:
                st.write('')
                ranking_args['normed_only'] = st.checkbox('Normed only',value=ranking_args['normed_only'])
            with cols[2]:
                st.write('')
                ranking_args['drop_zero'] = st.checkbox('Drop 0',value=ranking_args['drop_zero'],
                                                        help='If set, will drop all-zero columns')
            with cols[3]:
                st.write('')
                ranking_args['drop_na'] = st.checkbox('Drop N/A',value=ranking_args['drop_na'])

            cols = st.columns([2,2,2,2])
            with cols[0]:
                ranking_args['draw_margin'] = st.number_input('Draw margin',min_value=0.0,max_value=1.0,step=0.001,value=ranking_args['draw_margin'], format="%0.3f",
                    help='Margin for draw (tie)')
            with cols[1]:
                ranking_args['convergence_threshold'] = st.number_input('Convergence threshold',min_value=0.0,max_value=1.0,step=0.001,value=ranking_args['convergence_threshold'], format="%0.5f",
                help='Convergence threshold for iterations in methods like Markov chain')
            with cols[2]:
                ranking_args['markov_restart'] = st.number_input('Markov restart',min_value=0.0,max_value=1.0,step=0.001,value=ranking_args['markov_restart'], format="%0.3f")
            with cols[3]:
                ranking_args['metric_wise_merge'] = st.selectbox('Metric-wise merge',options=['None']+MERGE_METHODS,
                    help='If set, will rank for each metric separately and then aggregate by the "metric-wise merge" method, not available for markov method')
            
            cols = st.columns([5,1,1])
            with cols[0]:
                ranking_args['soft_filter_threshold'] = st.slider('Filtering Threshold',min_value=-1.0,max_value=1.0,step=0.001,value=float(ranking_args['soft_filter_threshold']), format="%0.3f",
                    help='If set, will filter out metrics with the highest difference in rating compared to a random metric lower than this, -1 (i.e. -100%) means no filtering')
            with cols[1]:
                st.write('')
                ranking_args['absolute_value_threshold'] = st.checkbox('Absolute',value=ranking_args['absolute_value_threshold'],
                    help='If set, will use absolute difference instead of relative difference `difference/random` for filtering')
            with cols[2]:
                st.write('')
                ranking_args['normed_difference'] = st.checkbox('Norm Diff.',value=ranking_args['normed_difference'],
                    help='If set, will use normed difference `|x-random|` instead of direct difference `x-random` for filtering')

            cols=st.columns(3)
            quadrant_args=U.safe_get_cfg_dict(select_cfg,'quadrant_args',DEFAULT_QUADRANT_ARGS)
            with cols[0]:
                st.write("##### Quadrant settings")
                ranking_args['quadrant_merge']=st.selectbox('Quadrant Merge',options=MERGE_METHODS,index=MERGE_METHODS.index(ranking_args.get('quadrant_merge','average')))
                quadrant_args['design_quantile']=st.slider('Design Quantile',min_value=0.0,max_value=1.0,step=0.01,value=quadrant_args['design_quantile'])
                quadrant_args['confidence_quantile']=st.slider('Confidence Quantile',min_value=0.0,max_value=1.0,step=0.01,value=quadrant_args['confidence_quantile'])

            design_explore_args=U.safe_get_cfg_dict(select_cfg,'design_explore_args',DEFAULT_DESIGN_EXPLORE_ARGS)
            with cols[1]:
                st.write("##### Design Exploration settings")
                design_explore_args['explore_prob']=st.slider('Design Explore Prob',min_value=0.0,max_value=1.0,step=0.01,value=design_explore_args['explore_prob'])
                design_explore_args['scheduler']=st.selectbox('Design Scheduler',options=SCHEDULER_OPTIONS,index=SCHEDULER_OPTIONS.index(design_explore_args['scheduler']))
                design_explore_args['background_noise']=st.slider('Design Background Noise',min_value=0.0,max_value=1.0,step=0.01,value=design_explore_args['background_noise'])
                
            verify_explore_args=U.safe_get_cfg_dict(select_cfg,'verify_explore_args',DEFAULT_VERIFY_EXPLORE_ARGS)
            with cols[2]:
                st.write("##### Verify Exploration settings")
                verify_explore_args['explore_prob']=st.slider('Verify Explore Prob',min_value=0.0,max_value=1.0,step=0.01,value=verify_explore_args['explore_prob'])
                verify_explore_args['scheduler']=st.selectbox('Verify Scheduler',options=SCHEDULER_OPTIONS,index=SCHEDULER_OPTIONS.index(verify_explore_args['scheduler']))
                verify_explore_args['background_noise']=st.slider('Verify Background Noise',min_value=0.0,max_value=1.0,step=0.01,value=verify_explore_args['background_noise'])

            select_cfg['ranking_args']=ranking_args
            select_cfg['quadrant_args']=quadrant_args
            select_cfg['design_explore_args']=design_explore_args
            select_cfg['verify_explore_args']=verify_explore_args
            st.form_submit_button("Save and Apply",
                on_click=apply_select_config,args=(evosys,select_cfg),
                # disabled=st.session_state.evo_running,
                disabled=st.session_state.is_demo,
                help='Before a design thread is started, the agent type of each role will be randomly selected based on the weights.'
            )   



def env_vars_settings(evosys):
    st.subheader("Environment Settings")

    env_vars={}
    with st.expander("Environment Variables",icon='🔑'):
        with st.form("Environment Variables"):
            st.info("**NOTE:** Leave the fields blank to use the default values. The settings here may not persist, so **better set them by exporting environment variables**.")
            col1,col2,col3,col4=st.columns(4)
            with col1:
                env_vars['DB_KEY_PATH']=st.text_input('Database Key Path',value=os.environ.get("DB_KEY_PATH",None),disabled=st.session_state.is_demo)
                env_vars['CKPT_DIR']=st.text_input('Checkpoint Directory',value=os.environ.get("CKPT_DIR"),disabled=st.session_state.is_demo)
                env_vars['DATA_DIR']=st.text_input('Data Directory',value=os.environ.get("DATA_DIR"),disabled=st.session_state.is_demo)
            with col2:
                env_vars['WANDB_API_KEY']=st.text_input('Weights & Biases API Key',type='password',disabled=st.session_state.is_demo)
                env_vars['HF_KEY']=st.text_input('Huggingface API Key',type='password',disabled=st.session_state.is_demo)
                env_vars['PINECONE_API_KEY']=st.text_input('Pinecone API Key',type='password',disabled=st.session_state.is_demo)
            with col3:
                env_vars['MY_OPENAI_KEY']=st.text_input('OpenAI API Key',type='password',disabled=st.session_state.is_demo)
                env_vars['ANTHROPIC_API_KEY']=st.text_input('Anthropic API Key',type='password',disabled=st.session_state.is_demo)
                env_vars['TOGETHER_API_KEY']=st.text_input('Together API Key',type='password',disabled=st.session_state.is_demo)
            with col4:
                env_vars['S2_API_KEY']=st.text_input('Semantic Scholar API Key',type='password',disabled=st.session_state.is_demo)
                env_vars['COHERE_API_KEY']=st.text_input('Cohere API Key',type='password',disabled=st.session_state.is_demo)
                env_vars['PERPLEXITY_API_KEY']=st.text_input('Perplexity API Key',type='password',disabled=st.session_state.is_demo)
                # optional: mathpix api key, aws keys

            if st.form_submit_button("Apply *(will not save any secrets)*",disabled=st.session_state.evo_running or st.session_state.is_demo):
                changed=apply_env_vars(evosys,env_vars)
                if changed:
                    evosys.reload()


def check_configs(evosys):
    st.write(f'### 🔧 Check Configurations for ```{evosys.evoname}```')
    st.caption("***NOTE:** Please check the configurations carefully, you may need to click save button multiple times to really save them due to some unknown reasons.*")
    col1,col2=st.columns(2)
    with col1:
        with st.expander("Check Select Config",expanded=False):
            st.write(evosys.select_cfg)
            st.info('Missing parts will apply default values')
    with col2:
        with st.expander("Check Design Config",expanded=False):
            st.write(evosys.design_cfg)
            st.info('Missing parts will apply default values')
    col3,col4=st.columns(2)
    with col3:
        with st.expander("Check Search Config",expanded=False):
            st.write(evosys.search_cfg)
            st.info('Missing parts will apply default values')
    with col4:
        with st.expander("Check Engine Config",expanded=False):
            st.write(evosys.ve_cfg)
            st.info('Missing parts will apply default values')


def local_experiments(evosys):
    
    col1,col2,col3,_=st.columns([1.5,1,1,1.8])
    with col1:
        st.header(f"Local Experiments")
    with col2:
        st.write('')
        if st.button("*Upload to Remote DB*",use_container_width=True,
            disabled=evosys.ptree.remote_db is None or st.session_state.is_demo):# or st.session_state.evo_running):
            sync_exps_to_db(evosys)
    with col3:
        st.write('')
        if st.button("*Download from Remote DB*",use_container_width=True,
            disabled=evosys.ptree.remote_db is None or st.session_state.is_demo):# or st.session_state.evo_running):
            sync_exps_from_db(evosys)
    
    def delete_exp(dir,evoname):
        if os.path.exists(dir):
            shutil.rmtree(dir)
        st.toast(f"Deleted directory: {dir}")
        if evosys.ptree.remote_db:
            delete_exp_from_db(evosys,evoname)
        # st.rerun()
    
    def switch_dir(evoname):
        evosys.switch_ckpt(evoname)
        st.toast(f"Switched to {evoname}")
        
    CKPT_DIR=os.environ.get('CKPT_DIR')
    setting=AU.get_setting()    

    def set_default(evoname):
        setting['default_namespace']=evoname
        AU.save_setting(setting)
        st.toast(f"Set {evoname} as default (for this machine)")
    
    default_namespace=setting.get('default_namespace','test_evo_000')

    notes = {
        'evo_exp_full_a': 'Full evolution',
        # 'evo_rtree_full_a': 'R-Tree',
        # 'evo_rand_full_a': 'Random',
        # 'evo_vani_full_a': 'Vani',
        # 'evo_base_full_a': 'Base',
        # "agent_full_a": 'Full',
        # "agent_nof_a": '',
        # "agent_nop_a": '',
        # "agent_noob_a": 'Noob',
        # "agent_base_c": 'Base',
    }


    experiments={}
    for ckpt in os.listdir(CKPT_DIR):
        if st.session_state.is_demo:
            if not ckpt in notes: continue
        if ckpt.startswith('.'): continue
        exp_dir=U.pjoin(CKPT_DIR,ckpt)
        ckpt_config_path=U.pjoin(exp_dir,'config.json')
        experiment={}
        experiment['namespace']=ckpt
        if not U.pexists(ckpt_config_path): 
            print(f"No config.json found in {exp_dir}, can be a temporary directory.")
            continue
        ckpt_config=U.load_json(ckpt_config_path)
        if 'params' not in ckpt_config: ckpt_config['params']={}
        ckpt_config['params']=U.init_dict(ckpt_config['params'],DEFAULT_PARAMS)
        experiment['design_budget']=ckpt_config['params']['design_budget']
        if experiment['design_budget']==0:
            experiment['design_budget']='♾️'
        if 'verify_budget' in ckpt_config['params']:
            experiment['verify_budget']=ckpt_config['params']['verify_budget']
        else:
            experiment['selection_ratio']=ckpt_config['params']['selection_ratio']
            verify_budget={}
            budget=ckpt_config['params']['n_target']
            for scale in ckpt_config['params']['scales'].split(',')[::-1]:
                verify_budget[scale]=int(np.ceil(budget))
                budget/=ckpt_config['params']['selection_ratio']
            experiment['verify_budget']=verify_budget
        experiment['budget_type']=ckpt_config['params']['budget_type']
        U.mkdir(U.pjoin(exp_dir,'db','sessions'))
        U.mkdir(U.pjoin(exp_dir,'db','designs'))
        experiment['local_sessions']=len(os.listdir(U.pjoin(exp_dir,'db','sessions')))
        experiment['local_designs']=len(os.listdir(U.pjoin(exp_dir,'db','designs')))
        experiment['use_remote_db']=ckpt_config.get('params',{}).get('use_remote_db',False)
        experiment['group_id']=ckpt_config.get('params',{}).get('group_id','default')
        experiment['benchmark_mode']=ckpt_config.get('params',{}).get('benchmark_mode',False)
        if st.session_state.is_demo:
            experiment['note']=notes[ckpt]

        if ckpt==default_namespace:
            default_btn=('Default',None,True)
        else:
            default_btn=('As Default',ft.partial(set_default,ckpt), False)
        if exp_dir==evosys.evo_dir:
            experiment['ICON']='🏠'
            experiment['BUTTON']=[
                ('Current',None,True),
                default_btn
            ]
            experiments[ckpt+' (Current)']=experiment
        else:
            experiment['BUTTON']=[
                ('Delete',ft.partial(delete_exp,exp_dir,ckpt), False),
                ('Switch',ft.partial(switch_dir,ckpt), False),
                default_btn
            ]
            if ckpt==default_namespace:
                experiments[ckpt+' (Default)']=experiment
            else:
                experiments[ckpt]=experiment



    if len(experiments)>0:
        AU.grid_view(st,experiments,per_row=3,spacing=0.05)
    else:
        st.info("No experiments found in the local directory. You may download from remote DB")



def config(evosys,project_dir):

    st.title("Experiment Management")

    # st.info("**NOTE:** Remember to upload your config to make the changes permanent and downloadable for nodes.")

    if st.session_state.is_demo:
        st.warning("***Demo mode:** You cannot change the config, its only for viewing.*")

    if st.session_state.listening_mode:
        st.warning("**WARNING:** You are running in listening mode. Modifying configurations may cause unexpected errors to any running evolution.")

    # if st.session_state.evo_running:
    #     st.warning("**NOTE:** Evolution system is running. You cannot modify the system configuration while the system is running.")


    env_vars_settings(evosys)
    evosys_settings(evosys)
    model_design_engine_settings(evosys)
    advanced_configs(evosys)
    check_configs(evosys)
    local_experiments(evosys)



    ################### Side bar ###################

    with st.sidebar:

        AU.running_status(st,evosys)

        def dump_config(_evosys):
            _config=U.load_json(U.pjoin(_evosys.evo_dir,'config.json'))
            _config['select_cfg']=_evosys.select_cfg
            _config['design_cfg']=_evosys.design_cfg
            if 'running_mode' in _config['design_cfg']:
                if not isinstance(_config['design_cfg']['running_mode'],str):
                    _config['design_cfg']['running_mode'] = _config['design_cfg']['running_mode'].value
            _config['search_cfg']=_evosys.search_cfg
            return json.dumps(_config,indent=4)

        st.download_button(
            label="Download your config",
            data=dump_config(evosys),
            file_name=f"{evosys.evoname}_config.json",
            mime="text/json",
            use_container_width=True
        )

        uploaded_file = st.file_uploader(
            "Upload your config",
            type=['json'],
            accept_multiple_files=False,
            # use_container_width=True
        )

        if uploaded_file is not None:
            uploaded_config = json.load(uploaded_file)
            with st.expander("Loaded Config",expanded=False):
                st.write(uploaded_config)
            st.button("Apply Uplaoded Config",on_click=apply_config,args=(evosys,uploaded_config,),
                disabled=st.session_state.evo_running or st.session_state.is_demo)


if __name__ == "__main__":
    from model_discovery.evolution import BuildEvolution
    import argparse
    from art import tprint

    AU.print_cli_title()

    parser = argparse.ArgumentParser()
    parser.add_argument('-u','--upload', action='store_true', help='Upload all local configs to remote DB')
    parser.add_argument('-d','--download', action='store_true', help='Download all configs from remote DB')
    args = parser.parse_args()

    setting=AU.get_setting()
    default_namespace=setting.get('default_namespace','test_evo_000')

    if args.upload:
        evosys = BuildEvolution(
            params={'evoname':default_namespace,'db_only':True,'no_agent':True}, 
            do_cache=False,
        )
        sync_exps_to_db(evosys)
    elif args.download:
        evosys = BuildEvolution(
            params={'evoname':default_namespace,'db_only':True,'no_agent':True}, 
            do_cache=False,
        )
        sync_exps_from_db(evosys)
    else:
        parser.print_help()



