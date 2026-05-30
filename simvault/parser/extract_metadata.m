function extract_metadata(model_dir, output_dir, lock_file_path)
% Crawls model_dir for .slx files, extracts metadata JSON per model.
% Skips files whose SHA matches simvault.lock.json.
%
% Usage:
%   extract_metadata('examples/pmsm_drive', 'extracted', 'simvault.lock.json')

if ~exist(output_dir, 'dir')
    mkdir(output_dir);
end

lock = load_lock(lock_file_path);

slx_files = dir(fullfile(model_dir, '**', '*.slx'));

for i = 1:length(slx_files)
    slx_path = fullfile(slx_files(i).folder, slx_files(i).name);

    % Skip build artifacts
    if contains(slx_path, {'slprj', '.git', '_archive'})
        continue;
    end

    current_hash = compute_sha256(slx_path);
    lock_key = strrep(slx_path, filesep, '/');

    if isfield(lock, 'files') && isfield(lock.files, matlab.lang.makeValidName(lock_key))
        stored = lock.files.(matlab.lang.makeValidName(lock_key));
        if strcmp(stored, current_hash)
            fprintf('Skipping (unchanged): %s\n', slx_files(i).name);
            continue;
        end
    end

    model_name = slx_files(i).name(1:end-4);
    fprintf('Extracting: %s\n', model_name);

    try
        load_system(slx_path);
        metadata = extract_model_metadata(model_name, slx_path, current_hash);
        out_file = fullfile(output_dir, [model_name '.json']);
        save_json(metadata, out_file);
        fprintf('  Saved: %s\n', out_file);

        % Update lock
        lock.files.(matlab.lang.makeValidName(lock_key)) = current_hash;
        save_lock(lock, lock_file_path);
    catch ME
        fprintf('  ERROR extracting %s: %s\n', model_name, ME.message);
    end

    try
        close_system(model_name, 0);
    catch
    end
end

fprintf('Done.\n');
end

% ---------------------------------------------------------------------------

function metadata = extract_model_metadata(model_name, slx_path, source_hash)
% Each .slx file becomes ONE subsystem entry — the whole model is the reusable unit.
metadata.model_name  = model_name;
metadata.source_file = slx_path;
metadata.source_hash = source_hash;

ss.id          = model_name;
ss.name        = model_name;
ss.path        = model_name;
ss.source_file = slx_path;
ss.source_hash = source_hash;

% Find the block carrying SimVault tags (the primary tagged subsystem)
tagged_block = find_tagged_block(model_name);

% Description / tags
if isempty(tagged_block)
    desc = '';
else
    try; desc = get_param(tagged_block, 'Description'); catch; desc = ''; end
end
ss.description    = desc;
ss.causal_summary = parse_causal_summary(desc, model_name);
ss.tags           = parse_tags(desc, tagged_block);

% Solver info
ss.solver = extract_solver_info(model_name);

% Block count (all blocks in model)
try
    all_blks = find_system(model_name, 'Type', 'block');
    ss.block_count = length(all_blks);
catch
    ss.block_count = -1;
end

ss.state_count = -1;

% Ports — model-level interface
ss.ports = extract_model_ports(model_name);

metadata.subsystems = {ss};
end

% ---------------------------------------------------------------------------

function tagged = find_tagged_block(model_name)
% Find the first block whose Description contains 'fidelity_tier'
tagged = '';
try
    all_ss = find_system(model_name, 'BlockType', 'SubSystem');
    for k = 1:length(all_ss)
        try
            d = get_param(all_ss{k}, 'Description');
            if contains(d, 'fidelity_tier')
                tagged = all_ss{k};
                return;
            end
        catch
        end
    end
    % Fallback: check the model description itself
    try
        d = get_param(model_name, 'Description');
        if contains(d, 'fidelity_tier')
            tagged = model_name;
        end
    catch
    end
catch
end
end

% ---------------------------------------------------------------------------

function tags = parse_tags(desc, blk_path)
tags.fidelity_tier   = extract_tag(desc, 'fidelity_tier',  infer_fidelity(blk_path));
tags.analysis_type   = extract_tag(desc, 'analysis_type',  'untagged');
tags.solver_contract = extract_tag(desc, 'solver_contract', 'continuous');
end

function val = extract_tag(desc, key, default_val)
pattern = [key '\s*:\s*(\S+)'];
tok = regexp(desc, pattern, 'tokens', 'once');
if ~isempty(tok)
    val = strtrim(tok{1});
else
    val = default_val;
end
end

function tier = infer_fidelity(blk_path)
% Infer from block count — rough heuristic
try
    n = length(find_system(blk_path, 'SearchDepth', 2));
    if n > 50
        tier = 'detailed';
    elseif n > 10
        tier = 'simplified';
    else
        tier = 'lookup';
    end
catch
    tier = 'untagged';
end
end

function summary = parse_causal_summary(desc, name)
% First non-tag line of description, or auto-generated
lines = strsplit(strtrim(desc), newline);
for i = 1:length(lines)
    line = strtrim(lines{i});
    if ~isempty(line) && ~contains(line, ':')
        summary = line;
        return;
    end
end
summary = ['Subsystem: ' name];
end

% ---------------------------------------------------------------------------

function solver_info = extract_solver_info(model_name)
solver_info.type        = 'continuous';
solver_info.name        = 'ode15s';
solver_info.sample_time = -1;
try
    solver_info.name        = get_param(model_name, 'Solver');
    solver_info.sample_time = str2double(get_param(model_name, 'FixedStep'));
    solver_type = get_param(model_name, 'SolverType');
    if contains(lower(solver_type), 'fixed')
        solver_info.type = 'discrete';
    else
        solver_info.type = 'continuous';
    end
catch
end
end

% ---------------------------------------------------------------------------

function ports = extract_model_ports(model_name)
% Build the external interface of a model by looking at:
%   1. Top-level Inport/Outport blocks  → named signal ports
%   2. SL2PS_* blocks anywhere          → signal inputs (physical bridge, named by block)
%   3. PS2SL_* blocks anywhere          → signal outputs (physical bridge, named by block)
% Physical (conserving) ports are not exposed at model boundary in most models.

ports = {};
seen = struct();

% 1. Top-level signal ports (Inport / Outport blocks)
try
    in_blocks  = find_system(model_name, 'SearchDepth', 1, 'BlockType', 'Inport');
    out_blocks = find_system(model_name, 'SearchDepth', 1, 'BlockType', 'Outport');

    for k = 1:length(in_blocks)
        blk = in_blocks{k};
        if strcmp(blk, model_name), continue; end
        port = make_signal_port(blk, 'input', model_name);
        key = matlab.lang.makeValidName(port.original_name);
        if ~isfield(seen, key)
            ports{end+1} = port;
            seen.(key) = true;
        end
    end
    for k = 1:length(out_blocks)
        blk = out_blocks{k};
        if strcmp(blk, model_name), continue; end
        port = make_signal_port(blk, 'output', model_name);
        key = matlab.lang.makeValidName(port.original_name);
        if ~isfield(seen, key)
            ports{end+1} = port;
            seen.(key) = true;
        end
    end
catch ME
    fprintf('  Warning (signal ports): %s\n', ME.message);
end

% 2. SL2PS_* blocks → they convert Simulink signals INTO the Simscape network.
%    Their signal input is the model's external input.
try
    all_blks = find_system(model_name, 'Type', 'block');
    for k = 1:length(all_blks)
        blk = all_blks{k};
        blk_name = get_param(blk, 'Name');
        if startsWith(blk_name, 'SL2PS_') || startsWith(blk_name, 'sl2ps_')
            % Strip prefix → meaningful port name
            raw_name = regexprep(blk_name, '^[Ss][Ll]2[Pp][Ss]_', '');
            port.original_name  = raw_name;
            port.canonical_name = '';
            port.direction      = 'input';
            port.port_type      = 'signal';
            port.domain         = 'signal';  % signal side (W, A, etc.)
            port.units          = infer_units_from_name(raw_name);
            key = matlab.lang.makeValidName(raw_name);
            if ~isfield(seen, key)
                ports{end+1} = port;
                seen.(key) = true;
            end
        end
    end
catch ME
    fprintf('  Warning (SL2PS): %s\n', ME.message);
end

% 3. PS2SL_* blocks → they convert Simscape physical signals OUT to Simulink.
try
    all_blks = find_system(model_name, 'Type', 'block');
    for k = 1:length(all_blks)
        blk = all_blks{k};
        blk_name = get_param(blk, 'Name');
        if startsWith(blk_name, 'PS2SL_') || startsWith(blk_name, 'ps2sl_')
            raw_name = regexprep(blk_name, '^[Pp][Ss]2[Ss][Ll]_', '');
            port.original_name  = raw_name;
            port.canonical_name = '';
            port.direction      = 'output';
            port.port_type      = 'signal';
            port.domain         = 'signal';
            port.units          = infer_units_from_name(raw_name);
            key = matlab.lang.makeValidName(raw_name);
            if ~isfield(seen, key)
                ports{end+1} = port;
                seen.(key) = true;
            end
        end
    end
catch ME
    fprintf('  Warning (PS2SL): %s\n', ME.message);
end

% 4. Sensor subsystems (TPS=torque, SpeedPS=speed, Tem_*=temperature, *PSSL=phys→signal)
%    Common naming patterns in Simscape test harnesses and component models.
SENSOR_PATTERNS = {'TPS', 'SpeedPS', 'Tem_', 'torqsens', 'omega_', 'n_shaft'};
OUTPUT_KEYWORDS = {'sens', 'ps', 'pssl', 'out', 'meas', 'read'};
try
    all_blks = find_system(model_name, 'Type', 'block');
    for k = 1:length(all_blks)
        blk = all_blks{k};
        blk_name = get_param(blk, 'Name');
        blk_lower = lower(blk_name);

        % Skip already-classified blocks
        if contains(blk_lower, {'sl2ps_', 'ps2sl_', 'ips', 'ipss'})
            continue;
        end

        matched = false;
        for p = SENSOR_PATTERNS
            if contains(blk_name, p{1})
                matched = true;
                break;
            end
        end
        if ~matched, continue; end

        % Classify direction: outputs if name suggests sensing/measurement
        is_output = any(cellfun(@(p) contains(blk_lower, p), OUTPUT_KEYWORDS));
        direction = 'output';
        if ~is_output, direction = 'input'; end

        port.original_name  = blk_name;
        port.canonical_name = '';
        port.direction      = direction;
        port.port_type      = 'signal';
        port.domain         = 'signal';
        port.units          = infer_units_from_name(blk_name);
        key = matlab.lang.makeValidName(blk_name);
        if ~isfield(seen, key)
            ports{end+1} = port;
            seen.(key) = true;
        end
    end
catch ME
    fprintf('  Warning (sensors): %s\n', ME.message);
end
end

function port = make_signal_port(blk, direction, model_name)
port.original_name  = get_param(blk, 'Name');
port.canonical_name = '';
port.direction      = direction;
port.port_type      = 'signal';
port.domain         = 'signal';
port.units          = 'unknown';
end

function units = infer_units_from_name(name)
n = lower(name);
if contains(n, 'loss') || contains(n, '_w') || contains(n, 'power') || contains(n, 'watt')
    units = 'W';
elseif contains(n, 'temp') || contains(n, 'temperature') || contains(n, '_k') || contains(n, 'kelvin')
    units = 'K';
elseif contains(n, 'current') || contains(n, '_a') || contains(n, 'amp')
    units = 'A';
elseif contains(n, 'torque') || contains(n, '_nm') || contains(n, 'trq')
    units = 'N*m';
elseif contains(n, 'speed') || contains(n, 'omega') || contains(n, 'rpm')
    units = 'rad/s';
elseif contains(n, 'volt') || contains(n, '_v') || contains(n, 'voltage')
    units = 'V';
else
    units = 'unknown';
end
end

% ---------------------------------------------------------------------------

function save_json(data, filepath)
json_str = jsonencode(data, 'PrettyPrint', true);
fid = fopen(filepath, 'w');
if fid == -1
    error('Cannot open file for writing: %s', filepath);
end
fwrite(fid, json_str, 'char');
fclose(fid);
end

function lock = load_lock(lock_file_path)
lock.files = struct();
if exist(lock_file_path, 'file')
    try
        raw = fileread(lock_file_path);
        parsed = jsondecode(raw);
        if isfield(parsed, 'files')
            lock.files = parsed.files;
        end
    catch
    end
end
end

function save_lock(lock, lock_file_path)
json_str = jsonencode(lock, 'PrettyPrint', true);
fid = fopen(lock_file_path, 'w');
fwrite(fid, json_str, 'char');
fclose(fid);
end

function hash = compute_sha256(filepath)
% Use shasum (available on macOS/Linux) for SHA-256
[status, result] = system(['shasum -a 256 "' filepath '"']);
if status == 0
    parts = strsplit(result);
    hash = strtrim(parts{1});
else
    % Fallback: use file size + mtime as a poor-man's hash
    info = dir(filepath);
    hash = sprintf('%d_%d', info.bytes, posixtime(info.datenum));
end
end
