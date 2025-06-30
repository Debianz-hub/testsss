#!/usr/bin/env python3
"""
Space Bedrock Server Launcher - Manual ZIP Version
-------------------------------------------------
Versión modificada para usar archivos ZIP subidos manualmente
"""

import os
import sys
import subprocess
import time
import logging
import zipfile
import signal
import threading
import shutil
import platform
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s: %(message)s',
    stream=sys.stdout
)

# CONFIGURACIÓN ACTUALIZADA
CONFIG = {
    "version": "manual",  # Versión manual
    "port": 19132,
    "data_dir": "space-data",
    "manual_zip_name": "bedrock-server.zip",  # Nombre esperado del ZIP manual
    "cloudflared_url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "timeout": 60,
    "max_retries": 3,
    "user_agent": "SpaceBedrockLauncher/2.1 (Manual-ZIP-Version)"
}

class SpaceBedrockManager:
    def __init__(self):
        self.server_process = None
        self.tunnel_process = None
        self.running = False
        self.is_codespaces = self.detect_codespaces()
        self.connection_info = {}
        
    def detect_codespaces(self):
        """Detecta si estamos ejecutando en GitHub Codespaces"""
        return os.getenv('CODESPACES') == 'true' or os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN') is not None
        
    def setup_signal_handlers(self):
        """Configura manejadores de señales para cierre limpio"""
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
    
    def signal_handler(self, signum, frame):
        """Maneja señales de cierre"""
        logging.info("Recibida señal de cierre, deteniendo servicios...")
        self.cleanup()
        sys.exit(0)

    def setup_environment(self):
        """Configuración inicial del entorno para Space"""
        logging.info("🛸 Preparando entorno Space...")
        
        data_path = Path(CONFIG["data_dir"])
        data_path.mkdir(exist_ok=True)
        
        # Configuraciones específicas para Codespaces
        if self.is_codespaces:
            logging.info("🌐 Detectado GitHub Codespaces")
            os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
            
        # Verificar espacio en disco
        try:
            disk_usage = shutil.disk_usage(data_path)
            free_gb = disk_usage.free / (1024**3)
            logging.info(f"💾 Espacio libre: {free_gb:.1f} GB")
            
            if free_gb < 1.0:
                logging.warning("⚠️ Poco espacio en disco disponible")
        except:
            pass
        
        return True

    def find_manual_zip(self):
        """Busca archivos ZIP del servidor Bedrock subidos manualmente"""
        data_path = Path(CONFIG["data_dir"])
        current_path = Path(".")
        
        # Buscar en varios nombres y ubicaciones posibles
        possible_names = [
            CONFIG["manual_zip_name"],
            "bedrock-server.zip",
            "bedrock_server.zip",
            "minecraft-server.zip",
            "server.zip"
        ]
        
        # Buscar en directorio actual y data_dir
        search_paths = [current_path, data_path]
        
        for search_path in search_paths:
            for zip_name in possible_names:
                zip_path = search_path / zip_name
                if zip_path.exists():
                    logging.info(f"📦 Encontrado ZIP manual: {zip_path}")
                    return zip_path
        
        # Buscar cualquier archivo .zip que contenga "bedrock" o "server"
        for search_path in search_paths:
            for zip_file in search_path.glob("*.zip"):
                zip_name_lower = zip_file.name.lower()
                if any(keyword in zip_name_lower for keyword in ["bedrock", "server", "minecraft"]):
                    logging.info(f"📦 Encontrado ZIP candidato: {zip_file}")
                    return zip_file
        
        return None

    def validate_bedrock_zip(self, zip_path):
        """Valida que el ZIP contiene un servidor Bedrock válido"""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                
                # Verificar archivos esenciales del servidor Bedrock
                required_files = ['bedrock_server']
                optional_files = ['server.properties', 'allowlist.json', 'permissions.json']
                
                has_server = any('bedrock_server' in f for f in file_list)
                if not has_server:
                    logging.error("❌ El ZIP no contiene el ejecutable 'bedrock_server'")
                    return False
                
                logging.info(f"✅ ZIP válido con {len(file_list)} archivos")
                
                # Mostrar contenido relevante
                bedrock_files = [f for f in file_list if not f.endswith('/')][:10]
                logging.info(f"📋 Archivos encontrados: {', '.join(bedrock_files[:5])}")
                if len(bedrock_files) > 5:
                    logging.info(f"    ... y {len(bedrock_files)-5} archivos más")
                
                return True
                
        except zipfile.BadZipFile:
            logging.error("❌ El archivo no es un ZIP válido")
            return False
        except Exception as e:
            logging.error(f"❌ Error validando ZIP: {e}")
            return False

    def install_bedrock_server(self):
        """Instala el servidor Bedrock desde ZIP manual"""
        server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
        
        if server_path.exists():
            logging.info("✅ Servidor ya instalado")
            return True
        
        # Buscar ZIP manual
        zip_path = self.find_manual_zip()
        if not zip_path:
            logging.error("❌ No se encontró archivo ZIP del servidor Bedrock")
            logging.info("📋 Instrucciones:")
            logging.info(f"   1. Descarga el servidor Bedrock desde: https://www.minecraft.net/download/server/bedrock")
            logging.info(f"   2. Sube el archivo ZIP como '{CONFIG['manual_zip_name']}' en este directorio")
            logging.info(f"   3. O colócalo en el directorio: {CONFIG['data_dir']}/")
            return False
        
        # Validar el ZIP
        if not self.validate_bedrock_zip(zip_path):
            return False
        
        # Extraer el servidor
        try:
            logging.info(f"📦 Extrayendo servidor desde: {zip_path.name}")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(CONFIG["data_dir"])
            
            # Verificar extracción
            if not server_path.exists():
                logging.error("❌ El servidor no se extrajo correctamente")
                return False
            
            # Hacer ejecutable
            server_path.chmod(0o755)
            
            logging.info("🎉 Servidor instalado correctamente desde ZIP manual")
            return True
            
        except Exception as e:
            logging.error(f"❌ Error al extraer: {e}")
            return False

    def setup_tunnel(self):
        """Configura el túnel según el entorno"""
        if self.is_codespaces:
            return self.setup_codespaces_tunnel()
        return self.setup_cloudflared()
    
    def setup_codespaces_tunnel(self):
        """Configura el túnel nativo de Codespaces"""
        logging.info("🚀 Configurando túnel nativo de Codespaces...")
        
        codespace_name = os.getenv('CODESPACE_NAME', 'space-server')
        github_domain = os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'preview.app.github.dev')
        
        self.connection_info = {
            "type": "codespaces",
            "address": f"{codespace_name}-{CONFIG['port']}.{github_domain}",
            "port": CONFIG['port'],
            "note": "Haz público el puerto en la pestaña 'PORTS'"
        }
        
        return True

    def download_cloudflared(self, destination):
        """Descarga Cloudflared si es necesario"""
        logging.info("⬇️ Descargando Cloudflared...")
        
        try:
            headers = {'User-Agent': CONFIG["user_agent"]}
            req = Request(CONFIG["cloudflared_url"], headers=headers)
            
            with urlopen(req, timeout=CONFIG["timeout"]) as response:
                with open(destination, 'wb') as f:
                    shutil.copyfileobj(response, f)
            
            destination.chmod(0o755)
            logging.info("✅ Cloudflared descargado correctamente")
            return True
            
        except Exception as e:
            logging.error(f"❌ Error descargando Cloudflared: {e}")
            return False

    def setup_cloudflared(self):
        """Configura Cloudflared para túnel externo"""
        cloudflared_path = Path(CONFIG["data_dir"]) / "cloudflared"
        
        if not cloudflared_path.exists():
            if not self.download_cloudflared(cloudflared_path):
                return False
        
        token = os.getenv("CLOUDFLARED_TOKEN")
        if not token:
            logging.warning("⚠️ CLOUDFLARED_TOKEN no configurado")
            logging.info("💡 Para usar túnel Cloudflare:")
            logging.info("   1. Crea una cuenta en Cloudflare Zero Trust")
            logging.info("   2. Configura un túnel UDP")
            logging.info("   3. Establece la variable: export CLOUDFLARED_TOKEN='tu-token'")
            return False
        
        try:
            logging.info("🌐 Iniciando túnel Cloudflare...")
            self.tunnel_process = subprocess.Popen(
                [str(cloudflared_path), "tunnel", "--protocol", "udp", "run", "--token", token],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            time.sleep(8)
            
            if self.tunnel_process.poll() is not None:
                logging.error("❌ El túnel Cloudflare falló al iniciar")
                return False
            
            self.connection_info = {
                "type": "cloudflare",
                "address": "Consulta los logs de Cloudflare",
                "port": CONFIG['port'],
                "note": "Túnel Cloudflare activo"
            }
            
            logging.info("✅ Túnel Cloudflare iniciado")
            return True
                
        except Exception as e:
            logging.error(f"❌ Error iniciando túnel: {e}")
            return False

    def configure_server(self):
        """Configura server.properties optimizado"""
        config_path = Path(CONFIG["data_dir"]) / "server.properties"
        
        server_config = {
            "server-name": "Space Bedrock Server",
            "gamemode": "survival",
            "difficulty": "normal",
            "allow-cheats": "false",
            "max-players": "10",
            "online-mode": "true",
            "server-port": str(CONFIG["port"]),
            "level-name": "Space-World",
            "default-player-permission-level": "member",
            "player-idle-timeout": "30",
            "view-distance": "12",
            "max-threads": "0",
            "server-authoritative-movement": "server-auth",
            "compression-threshold": "1"
        }
        
        logging.info("⚙️ Configurando servidor...")
        
        if config_path.exists():
            logging.info("🔄 Actualizando configuración existente...")
            existing_config = {}
            with open(config_path, 'r') as f:
                for line in f:
                    if '=' in line and not line.strip().startswith('#'):
                        key, value = line.strip().split('=', 1)
                        existing_config[key] = value
            
            # Mantener configuraciones existentes, solo actualizar las nuevas
            for key in list(server_config.keys()):
                if key in existing_config:
                    server_config[key] = existing_config[key]
        
        with open(config_path, 'w') as f:
            for key, value in server_config.items():
                f.write(f"{key}={value}\n")

    def generate_world_backup(self):
        """Crea un backup del mundo si existe"""
        world_dir = Path(CONFIG["data_dir"]) / "worlds"
        if not world_dir.exists() or not any(world_dir.iterdir()):
            logging.info("⚠️ No hay mundos para respaldar")
            return
            
        backup_dir = Path(CONFIG["data_dir"]) / "backups"
        backup_dir.mkdir(exist_ok=True)
        
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        backup_name = f"world-backup-{timestamp}.zip"
        backup_path = backup_dir / backup_name
        
        try:
            logging.info(f"💾 Creando backup: {backup_name}")
            with zipfile.ZipFile(backup_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(world_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        arcname = os.path.relpath(file_path, world_dir)
                        zipf.write(file_path, arcname)
            
            backup_size = backup_path.stat().st_size / (1024*1024)
            logging.info(f"✅ Backup creado: {backup_name} ({backup_size:.1f}MB)")
                        
        except Exception as e:
            logging.error(f"❌ Error creando backup: {str(e)}")

    def start_server(self):
        """Inicia el servidor Bedrock"""
        server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
        
        if not server_path.exists():
            logging.error("❌ Servidor no encontrado")
            return False
        
        os.chdir(CONFIG["data_dir"])
        logging.info("🚀 Iniciando servidor Space Bedrock...")
        
        try:
            self.running = True
            self.server_process = subprocess.Popen(
                ["./bedrock_server"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            def log_reader():
                while self.running and self.server_process.poll() is None:
                    if self.server_process.stdout:
                        line = self.server_process.stdout.readline()
                        if line:
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"[{timestamp}] {line.rstrip()}")
                    else:
                        time.sleep(0.1)
            
            log_thread = threading.Thread(target=log_reader, daemon=True)
            log_thread.start()
            
            self.server_process.wait()
            return True
            
        except KeyboardInterrupt:
            logging.info("⏹️ Deteniendo servidor...")
            return True
        except Exception as e:
            logging.error(f"❌ Error ejecutando servidor: {e}")
            return False
        finally:
            self.running = False
            self.generate_world_backup()

    def cleanup(self):
        """Limpia procesos al cerrar"""
        self.running = False
        
        if self.server_process and self.server_process.poll() is None:
            logging.info("🛑 Deteniendo servidor...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                logging.warning("⚠️ Forzando cierre del servidor...")
                self.server_process.kill()
        
        if self.tunnel_process and self.tunnel_process.poll() is None:
            logging.info("🔌 Deteniendo túnel...")
            self.tunnel_process.terminate()
            try:
                self.tunnel_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.tunnel_process.kill()

    def list_zip_files(self):
        """Lista archivos ZIP disponibles"""
        data_path = Path(CONFIG["data_dir"])
        current_path = Path(".")
        
        zip_files = []
        for search_path in [current_path, data_path]:
            for zip_file in search_path.glob("*.zip"):
                zip_files.append(zip_file)
        
        if zip_files:
            print("\n📦 Archivos ZIP encontrados:")
            for i, zip_file in enumerate(zip_files, 1):
                size_mb = zip_file.stat().st_size / (1024*1024)
                print(f"   {i}. {zip_file.name} ({size_mb:.1f}MB)")
        else:
            print("\n❌ No se encontraron archivos ZIP")
            print("💡 Sube un archivo ZIP del servidor Bedrock a este directorio")

    def show_menu(self):
        """Muestra el menú interactivo"""
        os.system('cls' if os.name == 'nt' else 'clear')
        print(f"""
        ███████╗██████╗  █████╗  ██████╗███████╗
        ██╔════╝██╔══██╗██╔══██╗██╔════╝██╔════╝
        ███████╗██████╔╝███████║██║     █████╗  
        ╚════██║██╔═══╝ ██╔══██║██║     ██╔══╝  
        ███████║██║     ██║  ██║╚██████╗███████╗
        ╚══════╝╚═╝     ╚═╝  ╚═╝ ╚═════╝╚══════╝
        
        Space Bedrock Server Launcher v2.1 (Manual ZIP)
        {'='*55}
        Versión: Manual ZIP
        Entorno: {'Codespaces' if self.is_codespaces else 'Local/VPS'}
        Directorio: {CONFIG['data_dir']}
        {'='*55}
        1. Iniciar servidor
        2. Ver archivos ZIP disponibles
        3. Configurar túnel
        4. Editar configuración
        5. Crear backup del mundo
        6. Reinstalar servidor (eliminar instalación actual)
        7. Salir
        {'='*55}
        """)
        return input("Seleccione una opción: ").strip()

    def reinstall_server(self):
        """Elimina la instalación actual para forzar reinstalación"""
        server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
        if server_path.exists():
            try:
                server_path.unlink()
                logging.info("🗑️ Servidor eliminado. Se reinstalará en el próximo inicio.")
                
                # También eliminar archivos relacionados si existen
                files_to_remove = [
                    "server.properties",
                    "allowlist.json", 
                    "permissions.json"
                ]
                
                for file_name in files_to_remove:
                    file_path = Path(CONFIG["data_dir"]) / file_name
                    if file_path.exists():
                        response = input(f"¿Eliminar {file_name}? (y/N): ").lower()
                        if response == 'y':
                            file_path.unlink()
                            logging.info(f"🗑️ {file_name} eliminado")
                
            except Exception as e:
                logging.error(f"❌ Error eliminando servidor: {e}")
        else:
            logging.info("⚠️ No hay servidor instalado")

    def edit_configuration(self):
        """Edita la configuración del servidor"""
        config_path = Path(CONFIG["data_dir"]) / "server.properties"
        if config_path.exists():
            editor = "nano" if sys.platform != "win32" else "notepad"
            try:
                subprocess.run([editor, str(config_path)])
                print("✅ Configuración guardada")
            except FileNotFoundError:
                print("⚠️ Editor no encontrado. Mostrando contenido del archivo:")
                with open(config_path, 'r') as f:
                    print(f.read())
        else:
            print("⚠️ Primero debe iniciar el servidor para generar la configuración")
        input("\nPresione Enter para continuar...")

    def run_interactive(self):
        """Ejecuta el launcher en modo interactivo"""
        self.setup_signal_handlers()
        self.setup_environment()
        
        while True:
            choice = self.show_menu()
            
            if choice == "1":
                if not self.install_bedrock_server():
                    input("\nError instalando servidor. Presione Enter...")
                    continue
                
                self.configure_server()
                
                if not self.setup_tunnel():
                    print("⚠️ Continuando sin túnel...")
                
                print("\n" + "="*60)
                if self.connection_info:
                    print("🔗 INFORMACIÓN DE CONEXIÓN:")
                    print(f"   Tipo: {self.connection_info['type'].upper()}")
                    print(f"   Dirección: {self.connection_info['address']}")
                    print(f"   Puerto: {self.connection_info['port']}")
                    print(f"   Nota: {self.connection_info['note']}")
                else:
                    print("⚠️ Servidor solo accesible localmente")
                    print(f"   Puerto local: {CONFIG['port']}")
                
                if self.is_codespaces:
                    print("\n📋 INSTRUCCIONES PARA CODESPACES:")
                    print("   1. Ve a la pestaña 'PORTS' en VS Code")
                    print(f"   2. Encuentra el puerto {CONFIG['port']}")
                    print("   3. Haz clic derecho → 'Port Visibility' → 'Public'")
                    print("   4. Usa la URL mostrada para conectarte")
                
                print("\n⚠️  PRESIONA CTRL+C PARA DETENER EL SERVIDOR")
                print("="*60 + "\n")
                
                self.start_server()
                self.cleanup()
                
            elif choice == "2":
                self.list_zip_files()
                input("\nPresione Enter para continuar...")
                
            elif choice == "3":
                if self.is_codespaces:
                    print("\nEn Codespaces se usa el túnel nativo automáticamente")
                else:
                    print("\nConfigurando túnel Cloudflare...")
                    if self.setup_cloudflared():
                        print("✅ Túnel configurado")
                    else:
                        print("❌ Error configurando túnel")
                input("\nPresione Enter para continuar...")
                
            elif choice == "4":
                self.edit_configuration()
                
            elif choice == "5":
                self.generate_world_backup()
                input("\nPresione Enter para continuar...")
                
            elif choice == "6":
                self.reinstall_server()
                input("\nPresione Enter para continuar...")
                
            elif choice == "7":
                print("\n👋 ¡Hasta pronto!")
                sys.exit(0)
                
            else:
                print("\n❌ Opción no válida")
                time.sleep(1)

def main():
    """Función principal"""
    try:
        manager = SpaceBedrockManager()
        manager.run_interactive()
    except Exception as e:
        logging.error(f"❌ Error crítico: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
