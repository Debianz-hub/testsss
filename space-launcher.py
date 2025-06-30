#!/usr/bin/env python3
"""
Space Bedrock Server Launcher - Manual ZIP Version (FIXED)
---------------------------------------------------------
Versión corregida con inicialización de mundo y dependencias
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
import json
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
    "user_agent": "SpaceBedrockLauncher/2.1 (Manual-ZIP-Version)",
    "world_name": "Space-World"  # Nuevo: Nombre del mundo predeterminado
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

    def install_cloudflared_apt(self):
        """Instala Cloudflared usando el repositorio oficial de Cloudflare (Debian/Ubuntu)"""
        try:
            logging.info("🔑 Añadiendo clave GPG de Cloudflare...")
            gpg_cmd = [
                "sudo", "mkdir", "-p", "--mode=0755", "/usr/share/keyrings"
            ]
            subprocess.run(gpg_cmd, check=True)
            
            curl_gpg = subprocess.Popen(
                ["curl", "-fsSL", "https://pkg.cloudflare.com/cloudflare-main.gpg"],
                stdout=subprocess.PIPE
            )
            tee_gpg = subprocess.Popen(
                ["sudo", "tee", "/usr/share/keyrings/cloudflare-main.gpg"],
                stdin=curl_gpg.stdout,
                stdout=subprocess.DEVNULL
            )
            curl_gpg.stdout.close()
            tee_gpg.communicate()
            
            logging.info("📦 Añadiendo repositorio de Cloudflared...")
            repo_cmd = [
                "sudo", "sh", "-c",
                "echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] "
                "https://pkg.cloudflare.com/cloudflared any main' > "
                "/etc/apt/sources.list.d/cloudflared.list"
            ]
            subprocess.run(repo_cmd, check=True)
            
            logging.info("🔄 Actualizando paquetes...")
            subprocess.run(["sudo", "apt-get", "update"], check=True)
            
            logging.info("⬇️ Instalando cloudflared...")
            subprocess.run(["sudo", "apt-get", "install", "-y", "cloudflared"], check=True)
            
            logging.info("✅ Cloudflared instalado correctamente via APT")
            return True
            
        except subprocess.CalledProcessError as e:
            logging.error(f"❌ Error durante instalación APT: {e}")
            return False

    def get_cloudflare_token(self):
        """Obtiene el token de múltiples fuentes seguras"""
        # 1. Intenta desde variables de entorno (GitHub Secrets)
        token = os.getenv("CLOUDFLARED_TOKEN")
        
        # 2. Si en Codespaces y no encontrado, verifica archivo temporal
        if not token and self.is_codespaces:
            token_path = Path("/workspaces/.codespaces/shared/environment-variables.json")
            if token_path.exists():
                try:
                    with open(token_path, 'r') as f:
                        env_vars = json.load(f)
                        token = env_vars.get("CLOUDFLARED_TOKEN", "")
                        if token:
                            logging.info("✅ Token obtenido desde GitHub Codespaces Secrets")
                except Exception as e:
                    logging.error(f"⚠️ Error leyendo variables de Codespaces: {e}")
        
        # 3. Último recurso: archivo local (NO RECOMENDADO)
        if not token:
            local_token = Path(CONFIG["data_dir"]) / "cloudflare-token.txt"
            if local_token.exists():
                try:
                    with open(local_token, 'r') as f:
                        token = f.read().strip()
                    logging.info(f"⚠️ Token obtenido desde archivo local: {local_token}")
                except Exception as e:
                    logging.error(f"❌ Error leyendo token local: {e}")
        
        return token

    def start_cloudflared_tunnel(self, cloudflared_path=None):
        """Inicia el túnel de Cloudflared"""
        token = self.get_cloudflare_token()
        if not token:
            logging.error("""
            ❌ ERROR: Token de Cloudflare no configurado
            === INSTRUCCIONES PARA GITHUB CODESPACES ===
            1. Ve a: https://github.com/<tu-usuario>/<tu-repo>/settings/secrets/codespaces
            2. Crea un secret llamado CLOUDFLARED_TOKEN
            3. Pega tu token de Cloudflare Zero Trust
            4. Reinicia este Codespace
            """)
            return False
        
        # Mostrar solo parte del token para seguridad
        token_display = f"{token[:4]}...{token[-4:]}" if token else "NO_TOKEN"
        logging.info(f"🔑 Usando token: {token_display}")
        
        try:
            cmd = ["cloudflared"] if cloudflared_path is None else [str(cloudflared_path)]
            cmd.extend([
                "tunnel", "--protocol", "udp", "run", "--token", token
            ])
            
            logging.info("🌐 Iniciando túnel Cloudflare...")
            self.tunnel_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            time.sleep(5)  # Esperar inicialización
            
            if self.tunnel_process.poll() is not None:
                logging.error("❌ El túnel Cloudflare falló al iniciar")
                return False
            
            logging.info("✅ Túnel Cloudflare iniciado")
            self.connection_info = {
                "type": "cloudflare",
                "address": f"Consulta: cloudflared tail",
                "port": CONFIG['port'],
                "note": "Túnel activo usando " + ("sistema" if cloudflared_path is None else "binario local")
            }
            return True
            
        except Exception as e:
            logging.error(f"❌ Error iniciando túnel: {e}")
            return False

    def setup_cloudflared(self):
        """Configura Cloudflared para túnel externo (versión mejorada)"""
        # Verificar si ya está instalado en el sistema
        if shutil.which("cloudflared"):
            logging.info("✅ Cloudflared ya está instalado en el sistema")
            return self.start_cloudflared_tunnel()
        
        # Intentar instalación via APT en sistemas Debian
        if platform.system() == "Linux" and any(os.path.exists(p) for p in ["/etc/debian_version", "/etc/apt/sources.list"]):
            logging.info("🐧 Detectado sistema Debian/Ubuntu, usando instalación APT...")
            if self.install_cloudflared_apt():
                return self.start_cloudflared_tunnel()
        
        # Fallback a instalación manual
        cloudflared_path = Path(CONFIG["data_dir"]) / "cloudflared"
        
        if not cloudflared_path.exists():
            if not self.download_cloudflared(cloudflared_path):
                return False
        
        return self.start_cloudflared_tunnel(cloudflared_path)

    def configure_server(self):
        """Configura server.properties optimizado y crea estructura de mundo"""
        data_dir = Path(CONFIG["data_dir"])
        config_path = data_dir / "server.properties"
        world_dir = data_dir / "worlds" / CONFIG["world_name"]
        
        # Crear estructura de directorios para el mundo
        world_dir.mkdir(parents=True, exist_ok=True)
        
        # Configuración optimizada del servidor
        server_config = {
            "server-name": "Space Bedrock Server",
            "gamemode": "survival",
            "difficulty": "normal",
            "allow-cheats": "false",
            "max-players": "10",
            "online-mode": "true",
            "server-port": str(CONFIG["port"]),
            "level-name": CONFIG["world_name"],  # Usar el nombre configurado
            "level-seed": "",  # Semilla aleatoria
            "default-player-permission-level": "member",
            "player-idle-timeout": "30",
            "view-distance": "12",
            "max-threads": "0",
            "server-authoritative-movement": "server-auth",
            "compression-threshold": "1",
            "content-log-file-enabled": "true",  # Nuevo: Habilitar logs
            "debug-output": "true"  # Nuevo: Más información en logs
        }
        
        logging.info("⚙️ Configurando servidor y mundo...")
        
        # Si existe configuración previa, conservar valores personalizados
        if config_path.exists():
            logging.info("🔄 Actualizando configuración existente...")
            existing_config = {}
            with open(config_path, 'r') as f:
                for line in f:
                    if '=' in line and not line.strip().startswith('#'):
                        key, value = line.strip().split('=', 1)
                        existing_config[key] = value
            
            # Conservar configuraciones existentes
            for key in list(server_config.keys()):
                if key in existing_config:
                    server_config[key] = existing_config[key]
        
        # Escribir nueva configuración
        with open(config_path, 'w') as f:
            for key, value in server_config.items():
                f.write(f"{key}={value}\n")
                
        # Crear archivos esenciales del mundo si no existen
        essential_files = [
            "level.dat", "levelname.txt", "world_icon.jpeg"
        ]
        
        for file in essential_files:
            file_path = world_dir / file
            if not file_path.exists():
                try:
                    file_path.touch()
                    logging.info(f"📄 Creando archivo de mundo: {file}")
                except Exception as e:
                    logging.error(f"❌ Error creando {file}: {e}")

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

    def install_dependencies(self):
        """Instala dependencias necesarias para Bedrock Server"""
        if platform.system() != "Linux":
            return True
            
        logging.info("🔍 Verificando dependencias del sistema...")
        required = ["libcurl4", "openssl", "ca-certificates"]
        
        try:
            # Verificar si ya están instalados
            check_cmd = ["dpkg", "-s"] + required
            result = subprocess.run(check_cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                logging.info("✅ Dependencias ya instaladas")
                return True
                
            logging.info("⬇️ Instalando dependencias necesarias...")
            install_cmd = ["sudo", "apt-get", "install", "-y"] + required
            subprocess.run(install_cmd, check=True)
            logging.info("✅ Dependencias instaladas correctamente")
            return True
        except Exception as e:
            logging.error(f"❌ Error instalando dependencias: {e}")
            logging.warning("⚠️ El servidor podría no funcionar correctamente")
            return False

    def is_port_in_use(self, port):
        """Comprueba si un puerto está en uso"""
        try:
            if platform.system() == "Windows":
                cmd = f"netstat -an | findstr :{port}"
            else:
                cmd = f"lsof -i:{port} -P -n | grep LISTEN"
                
            result = subprocess.run(cmd, shell=True, capture_output=True)
            return result.returncode == 0
        except Exception:
            return False

    def start_server(self):
        """Inicia el servidor Bedrock con comprobación de puerto"""
        server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
        
        if not server_path.exists():
            logging.error("❌ Servidor no encontrado")
            return False
        
        # Comprobar si el puerto está en uso
        if self.is_port_in_use(CONFIG["port"]):
            logging.error(f"❌ Puerto {CONFIG['port']} ya en uso!")
            logging.info("💡 Intenta cambiar el puerto en la configuración")
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
        Puerto: {CONFIG['port']}
        Mundo: {CONFIG['world_name']}
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
                
                # Instalar dependencias del sistema
                self.install_dependencies()
                
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
