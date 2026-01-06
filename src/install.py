import os
import shutil
import sys
import logging
from pathlib import Path

log = logging.getLogger(__name__)

class WorldInstaller:
    def __init__(self, config={}):
        self.config = config
    
    def get_saves_dir(self):
        ''' Returns the path to the Minecraft saves directory.
        
            :return: Path to Minecraft saves directory
        '''
        # Allow override from config
        if 'minecraft' in self.config and 'saves_dir' in self.config['minecraft']:
             return Path(self.config['minecraft']['saves_dir'])
        
        # Allow override from env
        if os.environ.get('MINECRAFT_SAVES_DIR'):
            return Path(os.environ['MINECRAFT_SAVES_DIR'])
            
        # Default locations
        if os.name == 'nt':
            return Path(os.environ.get('APPDATA', '')) / '.minecraft' / 'saves'
        elif sys.platform == 'darwin':
            return Path(os.path.expanduser('~/Library/Application Support/minecraft/saves'))
        else:
            return Path(os.path.expanduser('~/.minecraft/saves'))

    def install_action(self, target, source, env):
        ''' Installs the exported world to the Minecraft saves directory.

            :param target: SCons target list
            :param source: SCons source list
            :param env: SCons environment
        '''
        source_dir = Path(str(source[0])).parent
        target_dir = Path(str(target[0])).parent
        
        log.info(f"Installing world to: {target_dir}")
        
        if not source_dir.exists():
            log.error(f"Error: Source directory {source_dir} does not exist. Did export fail?")
            return 1

        if target_dir.exists() and any(target_dir.iterdir()):
             log.warning(f"Target directory already exists and is not empty: {target_dir}")
             try:
                # Flush stdout to ensure prompt appears
                sys.stdout.flush()
                response = input("Do you want to overwrite it? [y/N]: ").strip().lower()
                if response not in ['y', 'yes']:
                    log.info("Aborting installation by user request.")
                    raise RuntimeError("Installation aborted by user.")
             except EOFError:
                 log.info("Non-interactive mode. Overwriting...")

             # Remove existing directory if overwriting
             try:
                 shutil.rmtree(target_dir)
             except OSError as e:
                 log.error(f"Error removing existing directory: {e}")
                 raise

        try:
            shutil.copytree(source_dir, target_dir, dirs_exist_ok=True)
            log.info(f"Successfully installed world to {target_dir}")
        except Exception as e:
            log.error(f"Error installing world: {e}")
            raise
            
        return None
