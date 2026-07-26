# ========== ЗАПУСК ==========
if __name__ == "__main__":
    # Принудительно удаляем вебхук перед запуском polling
    import asyncio
    import threading
    
    async def delete_webhook_and_start():
        # Удаляем вебхук, если он был
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("✅ Вебхук удален, запускаем polling...")
        
        # Запускаем Flask в отдельном потоке для health check
        def run_flask():
            app.run(host="0.0.0.0", port=PORT, debug=False, use_reloader=False)
        
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        logger.info(f"Flask health check запущен на порту {PORT}")
        
        # Запускаем бота через polling
        await dp.start_polling(bot)
    
    try:
        asyncio.run(delete_webhook_and_start())
    except KeyboardInterrupt:
        logger.info("Бот остановлен")
    except Exception as e:
        logger.error(f"Ошибка: {e}")
