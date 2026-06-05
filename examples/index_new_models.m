% index_new_models.m
% Tags new models with SimVault metadata, then calls extract_metadata() per folder.
%
% Usage (from MATLAB Desktop):
%   cd /Users/soorajkrishnan/simscape-agent/SimVault
%   run('examples/index_new_models.m')
%
% After this completes, run from terminal:
%   simvault index extracted/ --skip-matlab

SIMSCAPE_ROOT = '/Users/soorajkrishnan/simscape-agent';
SIMVAULT_ROOT = fullfile(SIMSCAPE_ROOT, 'SimVault');
EXTRACTED_DIR = fullfile(SIMVAULT_ROOT, 'extracted');
LOCK_FILE     = fullfile(SIMVAULT_ROOT, 'simvault.lock.json');

% Parser must be on the path for extract_metadata and its local functions
addpath(fullfile(SIMVAULT_ROOT, 'simvault', 'parser'));

% ── Tagging manifest ─────────────────────────────────────────────────────────
% { slx_path, fidelity_tier, analysis_type, solver_contract }
% We tag the ROOT model (not a subsystem) — extract_metadata reads Description
% on any block that has the tags, falling back to root if needed.
tag_manifest = {
  fullfile(SIMSCAPE_ROOT,'IMFluxMotorCADExample','FEM_IM_FOC_FW.slx'), ...
    'detailed',    'drive_cycle',     'continuous';
  fullfile(SIMSCAPE_ROOT,'IMFluxMotorCADExample','IMFluxMotorCAD.slx'), ...
    'detailed',    'torque_accuracy', 'continuous';
  fullfile(SIMSCAPE_ROOT,'IPMSM','IPMSMTorque_rebuilt.slx'), ...
    'detailed',    'torque_accuracy', 'continuous';
  fullfile(SIMSCAPE_ROOT,'MotorThermalModel','PMSMThermal11Node.slx'), ...
    'detailed',    'thermal',         'continuous';
  fullfile(SIMSCAPE_ROOT,'demo','FEM_IM_OpenLoop_reference.slx'), ...
    'detailed',    'torque_accuracy', 'continuous';
  fullfile(SIMSCAPE_ROOT,'demo','VF_Demo_IM.slx'), ...
    'simplified',  'drive_cycle',     'continuous';
  fullfile(SIMSCAPE_ROOT,'FEM_PMSM','test_PMSM_FEM_foc.slx'), ...
    'detailed',    'drive_cycle',     'continuous';
  fullfile(SIMSCAPE_ROOT,'FEM_PMSM','test_PMSM_FEM_avg_dc.slx'), ...
    'simplified',  'efficiency',      'continuous';
};
% Note: FEM_PMSM_lib is a locked library — skip tagging, can still extract

fprintf('\n=== Step 1: Tagging %d models ===\n\n', size(tag_manifest,1));

for i = 1:size(tag_manifest,1)
    slx_path = tag_manifest{i,1};
    fidelity = tag_manifest{i,2};
    analysis = tag_manifest{i,3};
    solver   = tag_manifest{i,4};
    [~, model_name] = fileparts(slx_path);

    fprintf('[%d/%d] Tagging %s\n', i, size(tag_manifest,1), model_name);

    if ~exist(slx_path, 'file')
        fprintf('  SKIP — not found\n'); continue;
    end

    try
        load_system(slx_path);

        % Tag the root model Description — extract_metadata will find it
        existing = get_param(model_name, 'Description');
        new_tag  = sprintf('\nfidelity_tier: %s\nanalysis_type: %s\nsolver_contract: %s', ...
                           fidelity, analysis, solver);
        if ~contains(existing, 'fidelity_tier')
            set_param(model_name, 'Description', [existing new_tag]);
            save_system(model_name);
            fprintf('  Tagged root model\n');
        else
            fprintf('  Already tagged\n');
        end
        close_system(model_name, 0);
    catch ME
        fprintf('  WARNING: %s\n', ME.message);
        try; close_system(model_name, 0); catch; end
    end
end

% ── Extraction dirs ───────────────────────────────────────────────────────────
% extract_metadata scans a directory for *.slx files.
% We run it on each folder that has new models.
extract_dirs = {
  fullfile(SIMSCAPE_ROOT, 'IMFluxMotorCADExample');
  fullfile(SIMSCAPE_ROOT, 'IPMSM');
  fullfile(SIMSCAPE_ROOT, 'MotorThermalModel');
  fullfile(SIMSCAPE_ROOT, 'demo');
  fullfile(SIMSCAPE_ROOT, 'FEM_PMSM');   % includes FEM_PMSM_lib + harnesses
};

fprintf('\n=== Step 2: Extracting from %d directories ===\n\n', length(extract_dirs));

for i = 1:length(extract_dirs)
    d = extract_dirs{i};
    [~, dname] = fileparts(d);
    fprintf('[%d/%d] %s\n', i, length(extract_dirs), dname);
    try
        extract_metadata(d, EXTRACTED_DIR, LOCK_FILE);
        fprintf('  Done.\n');
    catch ME
        fprintf('  ERROR: %s\n', ME.message);
    end
end

fprintf('\n=== All done ===\n');
fprintf('Extracted JSONs in: %s\n', EXTRACTED_DIR);
fprintf('\nNow run in terminal:\n');
fprintf('  simvault index extracted/ --skip-matlab && simvault kb-update\n\n');
