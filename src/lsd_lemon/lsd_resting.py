from nipype.pipeline.engine import Node, Workflow, JoinNode
import nipype.interfaces.utility as util
import nipype.interfaces.io as nio
import nipype.interfaces.fsl as fsl
from func_preproc.strip_rois import strip_rois_func
from func_preproc.moco import create_moco_pipeline
from func_preproc.fieldmap_coreg import create_fmap_coreg_pipeline
from func_preproc.transform_timeseries import create_transform_pipeline
from func_preproc.denoise import create_denoise_pipeline

'''
Main workflow for lsd resting state preprocessing.
===================================================
Uses file structure set up by conversion script.

Equivalent to lemon resting but iterating over all 4 scans with their
respective files and parameters for distortion correction.
'''


def create_lsd_resting(subject, working_dir, out_dir, freesurfer_dir, data_dir, 
                    echo_space, te_diff, vol_to_remove, scans, epi_resolution,
                    TR, highpass, lowpass):
    
    # main workflow
    func_preproc = Workflow(name='lsd_resting')
    func_preproc.base_dir = working_dir
    func_preproc.config['execution']['crashdump_dir'] = func_preproc.base_dir + "/crash_files"
    
    
    # set fsl output type to nii.gz
    fsl.FSLCommand.set_default_output_type('NIFTI_GZ')
    
    # infosource to iterate over scans
    scan_infosource = Node(util.IdentityInterface(fields=['scan_id']), 
                      name='scan_infosource')
    scan_infosource.iterables=('scan_id', scans)
    
    # function node to get fieldmap information
    def fmap_info(scan_id):
        if scan_id=='rest1a':
            fmap_id='fmap1'
            pe_dir='y-'
        elif scan_id=='rest1b':
            fmap_id='fmap1'
            pe_dir='y'
        elif scan_id=='rest2a':
            fmap_id='fmap2'
            pe_dir='y-'
        elif scan_id=='rest2b':
            fmap_id='fmap2'
            pe_dir='y'
        return fmap_id, pe_dir
    
    fmap_infosource=Node(util.Function(input_names=['scan_id'],
                                       output_names=['fmap_id', 'pe_dir'],
                                       function=fmap_info),
                          name='fmap_infosource')
            
    # select files
    templates={'func': 'nifti/lsd_resting/{scan_id}.nii.gz',
               'fmap_phase' : 'nifti/lsd_resting/{fmap_id}_phase.nii.gz',
               'fmap_mag' : 'nifti/lsd_resting/{fmap_id}_mag.nii.gz',
               'anat_head' : 'preprocessed/anat/T1.nii.gz',
               'anat_brain' : 'preprocessed/anat/T1_brain.nii.gz',
               'func_mask' : 'preprocessed/anat/func_mask.nii.gz',
               }
    selectfiles = Node(nio.SelectFiles(templates,
                                       base_directory=data_dir),
                       name="selectfiles")
    
    
    # node to strip rois
    remove_vol = Node(util.Function(input_names=['in_file','t_min'],
                                    output_names=["out_file"],
                                    function=strip_rois_func),
                      name='remove_vol')
    remove_vol.inputs.t_min = vol_to_remove
    
    
    # workflow for motion correction
    moco=create_moco_pipeline()
    
    # workflow for fieldmap correction and coregistration
    fmap_coreg=create_fmap_coreg_pipeline()
    fmap_coreg.inputs.inputnode.fs_subjects_dir=freesurfer_dir
    fmap_coreg.inputs.inputnode.fs_subject_id=subject
    fmap_coreg.inputs.inputnode.echo_space=echo_space
    fmap_coreg.inputs.inputnode.te_diff=te_diff
    
    # workflow for applying transformations to timeseries
    transform_ts = create_transform_pipeline()
    transform_ts.inputs.inputnode.resolution=epi_resolution
    
    # workflow to denoise timeseries
    denoise = create_denoise_pipeline()
    denoise.inputs.inputnode.highpass_sigma= 1./(2*TR*highpass)
    denoise.inputs.inputnode.lowpass_sigma= 1./(2*TR*lowpass)
    # https://www.jiscmail.ac.uk/cgi-bin/webadmin?A2=ind1205&L=FSL&P=R57592&1=FSL&9=A&I=-3&J=on&d=No+Match%3BMatch%3BMatches&z=4 
    denoise.inputs.inputnode.tr = TR
    
    #sink to store files of single scans
    sink = Node(nio.DataSink(parameterization=False,
                             base_directory=out_dir,
                             substitutions=[('fmap1_phase_fslprepared', 'fieldmap'),
                                            ('fmap2_phase_fslprepared', 'fieldmap'),
                                            ('fieldmap_fslprepared_fieldmap_unmasked_vsm', 'shiftmap'),
                                            ('plot.rest_coregistered', 'outlier_plot'),
                                            ('filter_motion_comp_norm_compcor_art_dmotion', 'nuissance_matrix'),
                                            ('rest_realigned.nii.gz_abs.rms', 'rest_realigned_abs.rms'),
                                            ('rest_realigned.nii.gz.par','rest_realigned.par'),
                                            ('rest_realigned.nii.gz_rel.rms', 'rest_realigned_rel.rms'),
                                            ('rest_realigned.nii.gz_abs_disp', 'abs_displacement_plot'),
                                            ('rest_realigned.nii.gz_rel_disp', 'rel_displacment_plot'),
                                            ('art.rest_coregistered_outliers', 'outliers'),
                                            ('global_intensity.rest_coregistered', 'global_intensity'),
                                            ('norm.rest_coregistered', 'composite_norm'),
                                            ('stats.rest_coregistered', 'stats'),
                                            ('rest_denoised_bandpassed_norm.nii.gz', 'rest_preprocessed.nii.gz')
                                            ]),
                 name='sink')
    
    # connections
    func_preproc.connect([(scan_infosource, selectfiles, [('scan_id', 'scan_id')]),
                          (scan_infosource, fmap_infosource, [('scan_id', 'scan_id')]),
                          (fmap_infosource, selectfiles, [('fmap_id', 'fmap_id')]),
                          (fmap_infosource, fmap_coreg, [('pe_dir', 'inputnode.pe_dir')]),
                          (scan_infosource, sink, [('scan_id', 'container')]),
                          (selectfiles, remove_vol, [('func', 'in_file')]),
                          (remove_vol, moco, [('out_file', 'inputnode.epi')]),
                          (selectfiles, fmap_coreg, [('fmap_phase', 'inputnode.phase'),
                                                     ('fmap_mag', 'inputnode.mag'),
                                                     ('anat_head', 'inputnode.anat_head'),
                                                     ('anat_brain', 'inputnode.anat_brain')
                                                     ]),
                          (moco, fmap_coreg, [('outputnode.epi_mean', 'inputnode.epi_mean')]),
                          (remove_vol, transform_ts, [('out_file', 'inputnode.orig_ts')]),
                          (selectfiles, transform_ts, [('anat_head', 'inputnode.anat_head')]),
                          (moco, transform_ts, [('outputnode.mat_moco', 'inputnode.mat_moco')]),
                          (fmap_coreg, transform_ts, [('outputnode.fmap_fullwarp', 'inputnode.fullwarp')]),
                          (selectfiles, denoise, [('func_mask', 'inputnode.brain_mask'),
                                                  ('anat_brain', 'inputnode.anat_brain')]),
                          (fmap_coreg, denoise, [('outputnode.epi2anat_dat', 'inputnode.epi2anat_dat'),
                                                 ('outputnode.unwarped_mean_epi2fmap', 'inputnode.unwarped_mean')]),
                          (moco, denoise, [('outputnode.par_moco', 'inputnode.moco_par')]),
                          (transform_ts, denoise, [('outputnode.trans_ts','inputnode.epi_coreg')]),
                          (moco, sink, [#('outputnode.epi_moco', 'realign.@realigned_ts'),
                                        ('outputnode.par_moco', 'realign.@par'),
                                        ('outputnode.rms_moco', 'realign.@rms'),
                                        ('outputnode.mat_moco', 'realign.MAT.@mat'),
                                        ('outputnode.epi_mean', 'realign.@mean'),
                                        ('outputnode.rotplot', 'realign.plots.@rotplot'),
                                        ('outputnode.transplot', 'realign.plots.@transplot'),
                                        ('outputnode.dispplots', 'realign.plots.@dispplots'),
                                        ('outputnode.tsnr_file', 'realign.@tsnr')]),
                          (fmap_coreg, sink, [('outputnode.fmap','coregister.transforms2anat.@fmap'),
                                              #('outputnode.unwarpfield_epi2fmap', 'coregister.@unwarpfield_epi2fmap'),
                                              ('outputnode.unwarped_mean_epi2fmap', 'coregister.@unwarped_mean_epi2fmap'),
                                              ('outputnode.epi2fmap', 'coregister.@epi2fmap'),
                                              #('outputnode.shiftmap', 'coregister.@shiftmap'),
                                              ('outputnode.fmap_fullwarp', 'coregister.transforms2anat.@fmap_fullwarp'),
                                              ('outputnode.epi2anat', 'coregister.@epi2anat'),
                                              ('outputnode.epi2anat_mat', 'coregister.transforms2anat.@epi2anat_mat'),
                                              ('outputnode.epi2anat_dat', 'coregister.transforms2anat.@epi2anat_dat'),
                                              ('outputnode.epi2anat_mincost', 'coregister.@epi2anat_mincost')
                                              ]),
                          (transform_ts, sink, [#('outputnode.trans_ts', 'coregister.@full_transform_ts'),
                                                ('outputnode.trans_ts_mean', 'coregister.@full_transform_mean'),
                                                ('outputnode.resamp_brain', 'coregister.@resamp_brain')]),
                          (denoise, sink, [('outputnode.wmcsf_mask', 'denoise.mask.@wmcsf_masks'),
                                           ('outputnode.combined_motion','denoise.artefact.@combined_motion'),
                                           ('outputnode.outlier_files','denoise.artefact.@outlier'),
                                           ('outputnode.intensity_files','denoise.artefact.@intensity'),
                                           ('outputnode.outlier_stats','denoise.artefact.@outlierstats'),
                                           ('outputnode.outlier_plots','denoise.artefact.@outlierplots'),
                                           ('outputnode.mc_regressor', 'denoise.regress.@mc_regressor'),
                                           ('outputnode.comp_regressor', 'denoise.regress.@comp_regressor'),
                                           ('outputnode.mc_F', 'denoise.regress.@mc_F'),
                                           ('outputnode.mc_pF', 'denoise.regress.@mc_pF'),
                                           ('outputnode.comp_F', 'denoise.regress.@comp_F'),
                                           ('outputnode.comp_pF', 'denoise.regress.@comp_pF'),
                                           ('outputnode.brain_mask_resamp', 'denoise.mask.@brain_resamp'),
                                           ('outputnode.brain_mask2epi', 'denoise.mask.@brain_mask2epi'),
                                           ('outputnode.normalized_file', '@normalized')
                                           ])
                          ])
    
    #joinnode for concatenation
#     concatenate=JoinNode(fsl.Merge(dimension='t',
#                                    merged_file='rest_preprocessed_concat.nii.gz'),
#                                joinsource='scan_infosource',
#                                joinfield='in_files',
#                                name='concatenate')
#     #concatenate.plugin_args={'submit_specs': 'request_memory = 20000'}
#        
#     concat_sink=Node(nio.DataSink(parameterization=False,
#                                   base_directory=out_dir),
#                      name='concat_sink')
#        
#        
#     func_preproc.connect([(denoise, concatenate, [('outputnode.normalized_file', 'in_files')]),
#                           (concatenate, concat_sink, [('merged_file', '@rest_concat')])
#                           ])
        
    
    #func_preproc.write_graph(dotfilename='func_preproc.dot', graph2use='colored', format='pdf', simple_form=True)
    func_preproc.run()
    #func_preproc.run(plugin='CondorDAGMan')
    #func_preproc.run(plugin='MultiProc')