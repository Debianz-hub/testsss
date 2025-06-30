def install_bedrock_server(self):
     server_path = Path(CONFIG["data_dir"]) / "bedrock_server"
     
     if server_path.exists():
         logging.info("✅ Servidor ya instalado")
         return True
     
     zip_name = f"bedrock-server-{CONFIG['version']}.zip"
     zip_path = Path(CONFIG["data_dir"]) / zip_name
     
     if not zip_path.exists():
         logging.error(f"❌ Archivo ZIP no encontrado: {zip_name}")
         logging.info("ℹ️ Por favor sube manualmente el archivo ZIP del servidor Bedrock")
         logging.info(f"ℹ️ Nombre requerido: {zip_name}")
         return False
     
     # Extraer el servidor
     try:
         logging.info(f"📦 Extrayendo {zip_name}...")
         with zipfile.ZipFile(zip_path, 'r') as zip_ref:
             zip_ref.extractall(CONFIG["data_dir"])
         
         # Verificar extracción
         if not server_path.exists():
             logging.error("❌ El servidor no se extrajo correctamente")
             return False
         
         # Hacer ejecutable
         server_path.chmod(0o755)
         
         logging.info("🎉 Servidor instalado correctamente")
         return True
     except Exception as e:
         logging.error(f"❌ Error al extraer: {e}")
         return False
