% tag_models_for_simvault.m
% Run once from SimVault/ before calling simvault index.
% Adds SimVault Description tags to each key subsystem in the sample models.
%
% Usage (from SimVault/ directory in MATLAB):
%   cd examples/pmsm_drive
%   run('../tag_models_for_simvault.m')

orig_dir = pwd;
examples_dir = fullfile(fileparts(mfilename('fullpath')), 'pmsm_drive');
cd(examples_dir);

tags = {
  % {model_file,          subsystem_name,       fidelity_tier,  analysis_type,     solver_contract}
  'PMSM_FEM',           'PMSM_FEM',           'detailed',     'torque_accuracy', 'continuous'
  'PMSM_avg',           'PMSM_FEM_avg',       'simplified',   'efficiency',      'continuous'
  'MotorThermal11Node', 'MotorThermalModel',  'detailed',     'thermal',         'continuous'
  'FOCController',      'FOCController',      'detailed',     'drive_cycle',     'continuous'
  'FEM_IM',             'FEM_IM',             'detailed',     'torque_accuracy', 'continuous'
  'FEM_IM_FOC_MA',      'FEM_IM_FOC',         'detailed',     'drive_cycle',     'continuous'
};

for i = 1:size(tags, 1)
    model_file = tags{i,1};
    subsys     = tags{i,2};
    fidelity   = tags{i,3};
    analysis   = tags{i,4};
    solver     = tags{i,5};

    try
        load_system(model_file);
        block_path = [model_file '/' subsys];

        % Verify block exists
        try
            get_param(block_path, 'Name');
        catch
            % Try finding any top-level subsystem
            all_ss = find_system(model_file, 'SearchDepth', 1, 'BlockType', 'SubSystem');
            if ~isempty(all_ss)
                block_path = all_ss{1};
                fprintf('  Using block: %s\n', block_path);
            else
                fprintf('  WARNING: No subsystem found in %s, tagging root model\n', model_file);
                block_path = model_file;
            end
        end

        existing = get_param(block_path, 'Description');
        new_tag = sprintf('\nfidelity_tier: %s\nanalysis_type: %s\nsolver_contract: %s', ...
                          fidelity, analysis, solver);

        if ~contains(existing, 'fidelity_tier')
            set_param(block_path, 'Description', [existing new_tag]);
            save_system(model_file);
            fprintf('Tagged: %s / %s\n', model_file, block_path);
        else
            fprintf('Already tagged: %s / %s\n', model_file, block_path);
        end

        close_system(model_file, 0);
    catch ME
        fprintf('ERROR tagging %s: %s\n', model_file, ME.message);
        try; close_system(model_file, 0); catch; end
    end
end

cd(orig_dir);
disp('Done tagging models.');
