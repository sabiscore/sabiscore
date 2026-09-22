"""
Background task to initialize and run data ingestion service
Run with: python -m backend.src.cli.start_ingestion
"""

import asyncio
import signal
import sys
import logging

from ..services.data_ingestion import ingestion_service
from ..core.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


async def main():
    """Main entry point for data ingestion service"""
    logger.info("=== SabiScore Data Ingestion Service ===")

    # Setup signal handlers for graceful shutdown
    asyncio.get_running_loop()

    def shutdown_handler(sig, frame):
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(ingestion_service.stop())

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    try:
        # Start ingestion service
        await ingestion_service.start()

        logger.info("Data ingestion service running. Press Ctrl+C to stop.")

        # Keep running until stopped
        while ingestion_service._running:
            await asyncio.sleep(1)

    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)
    finally:
        await ingestion_service.stop()
        logger.info("Data ingestion service stopped")


if __name__ == "__main__":
    asyncio.run(main())
