#!/usr/bin/env python3
"""
Space Bedrock Server Launcher - Ultimate Fusion
------------------------------------------------
Combina lo mejor de ambos enfoques con optimización para Codespaces
y características avanzadas de gestión de servidores.
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
import json
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

# Configuración específica para Space
CONFIG = {
    "version": "1.21.44.01",
    "port": 19132,
    "data_dir": "space-data",
    "mirrors": [
        "https://minecraft.azureedge.net/bin-linux/",
        "https://cdn-raw.overwolf.com/",
        "https://bedrock-servers.s3.amazonaws.com/"
    ],
    "cloudflared_url": "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    "timeout": 45,
    "max_retries": 5,
    "user_agent": "SpaceBedrockLauncher/1.0",
    "default_ram": "1G" if platform.machine() == "aarch64" else "2G"
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

    def install_dependencies(self):
        """Instala dependencias con múltiples métodos de respaldo"""
        try:
            import requests
            return requests
        except ImportError:
            logging.warning("Dependencias no disponibles, intentando instalación...")
        
        install_methods = [
            # Método 1: pip install con --user
            [sys.executable, "-m", "pip", "install", "--user", "requests"],
            
            # Método 2: pip install global
            [sys.executable, "-m", "pip", "install", "requests"],
            
            # Método 3: apt-get (solo Linux)
            ["sudo", "apt-get", "install", "-y", "python3-requests"] if sys.platform == "linux" else None
        ]
        
        for method in install_methods:
            if method is None:
                continue
                
            try:
                result = subprocess.run(
                    method,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=120
                )
                if result.returncode == 0:
                    import requests
                    logging.info("Dependencias instaladas correctamente")
                    return requests
                else:
                    logging.warning(f"Intento fallido: {result.stderr.decode()}")
            except Exception as e:
                logging.warning(f"Error en instalación: {str(e)}")
        
        logging.warning("No se pudieron instalar todas las dependencias, usando respaldo")
        return None

    def download_file(self, url, destination):
        """Descarga con múltiples métodos de respaldo"""
        requests_module = self.install_dependencies()
        
        # Intentar con requests si está disponible
        if requests_module:
            try:
                logging.info(f"Descargando con requests: {url}")
                response = requests_module.get(
                    url, 
                    stream=True, 
                    timeout=CONFIG["timeout"],
                    headers={'User-Agent': CONFIG["user_agent"]}
                )
                response.raise_for_status()
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                with open(destination, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                progress = (downloaded / total_size) * 100
                                print(f"\rProgreso: {progress:.1f}%", end='', flush=True)
                
                print()
                return True
            except Exception as e:
                logging.warning(f"Requests falló: {str(e)}")
        
        # Respaldo con urllib
        try:
            logging.info(f"Descargando con urllib: {url}")
            req = Request(url, headers={'User-Agent': CONFIG["user_agent"]})
            
            with urlopen(req, timeout=CONFIG["timeout"]) as response:
                total_size = int(response.headers.get('Content-Length', 0))
                downloaded = 0
                
                with open(destination, 'wb') as f:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            print(f"\rProgreso: {progress:.1f}%", end='', flush=True)
            
            print()
            return True
        except Exception as e:
            logging.error(f"Error en descarga: {str(e)}")
            return False

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
            
            if free_gb < 2.0:
                logging.warning("⚠️ Poco espacio en disco disponible")
        except:
            pass
        
        return True

    def install_bedrock_server(self):
        """Instala el servidor Bedrock con verificación de integridad"""
        server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
        
        if server_path.exists():
            logging.info("✅ Servidor ya instalado")
            return True
        
        zip_name = f"bedrock-server-{CONFIG['version']}.zip"
        zip_path = Path(CONFIG["data_dir"]) / zip_name
        
        # Intentar descargar desde los mirrors
        for i, mirror in enumerate(CONFIG["mirrors"]):
            url = f"{mirror}{zip_name}"
            logging.info(f"🔍 Probando mirror {i+1}/{len(CONFIG['mirrors'])}: {mirror}")
            
            if self.download_file(url, zip_path):
                # Verificar integridad del archivo
                if zip_path.stat().st_size < 50 * 1024 * 1024:  # 50MB
                    logging.warning("⚠️ Archivo demasiado pequeño, posible descarga corrupta")
                    continue
                break
        else:
            logging.error("❌ Falló la descarga desde todos los mirrors")
            return False
        
        # Extraer usando zipfile
        try:
            logging.info("📦 Extrayendo servidor Bedrock...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(CONFIG["data_dir"])
            
            # Verificar extracción
            if not server_path.exists():
                logging.error("❌ El servidor no se extrajo correctamente")
                return False
            
            # Hacer ejecutable
            server_path.chmod(0o755)
            
            # Limpiar archivo zip
            zip_path.unlink()
            
            logging.info("🎉 Servidor instalado correctamente")
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
        
        # Obtener información de Codespaces
        codespace_name = os.getenv('CODESPACE_NAME', 'space-server')
        github_domain = os.getenv('GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN', 'preview.app.github.dev')
        
        self.connection_info = {
            "type": "codespaces",
            "address": f"{codespace_name}-{CONFIG['port']}.{github_domain}",
            "port": CONFIG['port'],
            "note": "Haz público el puerto en la pestaña 'PORTS'"
        }
        
        return True

    def setup_cloudflared(self):
        """Configura Cloudflared para túnel externo"""
        cloudflared_path = Path(CONFIG["data_dir"]) / "cloudflared"
        
        # Descargar cloudflared si no existe
        if not cloudflared_path.exists():
            logging.info("⬇️ Descargando Cloudflared...")
            if not self.download_file(CONFIG["cloudflared_url"], cloudflared_path):
                logging.error("❌ Error descargando Cloudflared")
                return False
            cloudflared_path.chmod(0o755)
        
        # Verificar token
        token = os.getenv("CLOUDFLARED_TOKEN")
        if not token:
            logging.warning("⚠️ CLOUDFLARED_TOKEN no configurado")
            return False
        
        # Iniciar túnel
        try:
            logging.info("🌐 Iniciando túnel Cloudflare...")
            self.tunnel_process = subprocess.Popen(
                [str(cloudflared_path), "tunnel", "--protocol", "udp", "run", "--token", token],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Esperar inicialización
            time.sleep(8)
            
            if self.tunnel_process.poll() is not None:
                logging.error("❌ El túnel Cloudflare falló al iniciar")
                return False
            
            # Obtener información de conexión
            try:
                result = subprocess.run(
                    [str(cloudflared_path), "access", "tcp", "--url", f"udp://localhost:{CONFIG['port']}"],
                    capture_output=True,
                    text=True,
                    timeout=15
                )
                if "https://" in result.stdout:
                    for line in result.stdout.split('\n'):
                        if "https://" in line:
                            address = line.strip().split()[-1].replace('https://', '')
                            self.connection_info = {
                                "type": "cloudflare",
                                "address": address,
                                "port": CONFIG['port'],
                                "note": "Túnel Cloudflare activo"
                            }
                            break
            except:
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
        """Configura server.properties optimizado para Space"""
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
            "max-threads": "0",  # 0 = automático
            "server-authoritative-movement": "server-auth",
            "compression-threshold": "1"
        }
        
        logging.info("⚙️ Configurando servidor Space...")
        
        # Si el archivo ya existe, mantener configuraciones personalizadas
        if config_path.exists():
            logging.info("🔄 Actualizando configuración existente...")
            existing_config = {}
            with open(config_path, 'r') as f:
                for line in f:
                    if '=' in line:
                        key, value = line.strip().split('=', 1)
                        existing_config[key] = value
            
            # Conservar configuraciones personalizadas
            for key in list(server_config.keys()):
                if key in existing_config:
                    server_config[key] = existing_config[key]
        
        # Escribir configuración
        with open(config_path, 'w') as f:
            for key, value in server_config.items():
                f.write(f"{key}={value}\n")

    def generate_world_backup(self):
        """Crea un backup del mundo si existe"""
        world_dir = Path(CONFIG["data_dir"]) / "worlds"
        if not world_dir.exists() or not any(world_dir.iterdir()):
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
            
            # Mostrar logs en tiempo real
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
            
            # Esperar a que termine el proceso
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

    def show_menu(self):
        """Muestra el menú interactivo de Space"""
        clear_screen()
        print(f"""
        ███████╗██████╗  █████╗  ██████╗███████╗
        ██╔════╝██╔══██╗██╔══██╗██╔════╝██╔════╝
        ███████╗██████╔╝███████║██║     █████╗  
        ╚════██║██╔═══╝ ██╔══██║██║     ██╔══╝  
        ███████║██║     ██║  ██║╚██████╗███████╗
        ╚══════╝╚═╝     ╚═╝  ╚═╝ ╚═════╝╚══════╝
        
        Space Bedrock Server Launcher
        {'='*50}
        Versión: {CONFIG['version']}
        Entorno: {'Codespaces' if self.is_codespaces else 'Local/VPS'}
        Directorio: {CONFIG['data_dir']}
        {'='*50}
        1. Iniciar servidor
        2. Cambiar versión
        3. Configurar túnel
        4. Editar configuración
        5. Crear backup del mundo
        6. Salir
        {'='*50}
        """)
        return input("Seleccione una opción: ").strip()

    def change_version(self):
        """Cambia la versión del servidor"""
        new_version = input(f"\nVersión actual: {CONFIG['version']}\nNueva versión: ").strip()
        if new_version:
            CONFIG["version"] = new_version
            print(f"✅ Versión actualizada a {CONFIG['version']}")
        else:
            print("❌ No se especificó versión")
        input("\nPresione Enter para continuar...")

    def edit_configuration(self):
        """Edita la configuración del servidor"""
        config_path = Path(CONFIG["data_dir"]) / "server.properties"
        if config_path.exists():
            editor = "nano" if sys.platform != "win32" else "notepad"
            subprocess.run([editor, str(config_path)])
            print("✅ Configuración guardada")
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
                
                print("\n" + "="*50)
                if self.connection_info:
                    print("🔗 INFORMACIÓN DE CONEXIÓN:")
                    print(f"   Tipo: {self.connection_info['type'].upper()}")
                    print(f"   Dirección: {self.connection_info['address']}")
                    print(f"   Puerto: {self.connection_info['port']}")
                    print(f"   Nota: {self.connection_info['note']}")
                else:
                    print("⚠️ No se obtuvo información de conexión")
                
                if self.is_codespaces:
                    print("\n📋 INSTRUCCIONES PARA CODESPACES:")
                    print("   1. Ve a la pestaña 'PORTS' en VS Code")
                    print(f"   2. Encuentra el puerto {CONFIG['port']}")
                    print("   3. Haz clic derecho → 'Port Visibility' → 'Public'")
                    print("   4. Usa la URL mostrada para conectarte")
                
                print("\n⚠️  PRESIONA CTRL+C PARA DETENER EL SERVIDOR")
                print("="*50 + "\n")
                
                self.start_server()
                self.cleanup()
                
            elif choice == "2":
                self.change_version()
                
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
                print("✅ Backup creado correctamente")
                input("\nPresione Enter para continuar...")
                
            elif choice == "6":
                print("\n👋 ¡Hasta pronto!")
                sys.exit(0)
                
            else:
                print("\n❌ Opción no válida")
                time.sleep(1)

def clear_screen():
    """Limpia la pantalla de la terminal"""
    os.system('cls' if os.name == 'nt' else 'clear')

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
