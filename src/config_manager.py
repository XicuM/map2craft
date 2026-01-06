import yaml
from pathlib import Path
import logging

log = logging.getLogger(__name__)

def deep_merge(base, overlay):
    """Recursively merge two dictionaries; overlay values take precedence."""
    if not isinstance(base, dict) or not isinstance(overlay, dict):
        return overlay
    
    result = base.copy()
    for key, value in overlay.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_name=None, base_path='.'):
    '''Load and merge default.yaml with an optional environment-specific YAML.'''
    config_dir = Path(base_path)/'config'
    default_path = config_dir/'default.yaml'
    
    if not default_path.exists():
        raise FileNotFoundError(f'Required base config missing: {default_path}')
        
    config = yaml.safe_load(default_path.read_text())
    
    if config_name:
        specific_path = config_dir/f'{config_name}.yaml'
        if specific_path.exists():
            log.info(f'Loading specific config: {specific_path}')
            specific_data = yaml.safe_load(specific_path.read_text())
            config = deep_merge(config, specific_data)
        else:
            log.warning(f'{config_name}.yaml not found at {specific_path}. Using default.')
            
    return config
