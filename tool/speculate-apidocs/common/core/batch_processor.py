import asyncio
import time
from typing import List, Any, Callable, Awaitable, TypeVar, Dict, Optional
import logging

T = TypeVar('T')
R = TypeVar('R')

class BatchProcessor:
    """
    Processes items in batches for efficient parallel execution.
    Handles batching, concurrency control, and error management.
    
    Enhanced with request spacing to prevent thundering herd and rate limiting issues.
    """
    
    def __init__(self, 
                 default_batch_size: int = 30, 
                 max_concurrency: Optional[int] = None,
                 retry_failed: bool = False,
                 max_retries: int = 3,
                 request_spacing: float = 0.0,  # New parameter for spacing between requests
                 adaptive_spacing: bool = False,  # New parameter for adaptive spacing
                 min_spacing: float = 0.1,  # Minimum spacing when adaptive
                 max_spacing: float = 2.0):  # Maximum spacing when adaptive
        """
        Initialize batch processor.
        
        Args:
            default_batch_size: Default number of items per batch
            max_concurrency: Maximum number of concurrent tasks (None = unlimited)
            retry_failed: Whether to retry failed items
            max_retries: Maximum number of retries for failed items
            request_spacing: Fixed delay in seconds between starting each request (0 = disabled)
            adaptive_spacing: If True, automatically adjust spacing based on rate limit events
            min_spacing: Minimum spacing when using adaptive spacing
            max_spacing: Maximum spacing when using adaptive spacing
        """
        self.default_batch_size = default_batch_size
        self.max_concurrency = max_concurrency
        self.retry_failed = retry_failed
        self.max_retries = max_retries
        
        # Request spacing attributes
        self.request_spacing = request_spacing
        self.adaptive_spacing = adaptive_spacing
        self.min_spacing = min_spacing
        self.max_spacing = max_spacing
        self.current_spacing = request_spacing if request_spacing > 0 else min_spacing
        
        # Lock for coordinating request timing
        self.request_lock = asyncio.Lock()
        self.last_request_time = 0
        
        # Rate limit tracking for adaptive spacing
        self.rate_limit_events = []
        self.rate_limit_window = 60  # Track events in last 60 seconds
        
        # Logger
        self.logger = logging.getLogger(__name__)
    
    async def process_in_batches(self, 
                                 items: List[T], 
                                 processor_func: Callable[[T], Awaitable[R]], 
                                 batch_size: Optional[int] = None,
                                 semaphore: Optional[asyncio.Semaphore] = None,
                                 concurrency: Optional[int] = None,
                                 request_spacing: Optional[float] = None) -> List[R]:
        """
        Process items in batches using the provided processor function.
        
        Args:
            items: List of items to process
            processor_func: Async function to process each item
            batch_size: Size of each batch (overrides default if provided)
            semaphore: Custom semaphore for concurrency control
            concurrency: Override max_concurrency for this batch
            request_spacing: Override request spacing for this batch
            
        Returns:
            List of results from processor function
        """
        if not concurrency:
            concurrency = self.max_concurrency
        if not items:
            return []
        
        # Use provided batch size or default
        batch_size = batch_size or self.default_batch_size
        
        # Use provided request spacing or instance default
        if request_spacing is not None:
            effective_spacing = request_spacing
        else:
            effective_spacing = self.current_spacing if self.adaptive_spacing else self.request_spacing
        
        # Create semaphore if max_concurrency is set and no custom semaphore provided
        if concurrency and not semaphore:
            semaphore = asyncio.Semaphore(concurrency)
        
        # Create batches
        batches = [items[i:i + batch_size] for i in range(0, len(items), batch_size)]
        
        # Process all batches
        results = []
        for batch_idx, batch in enumerate(batches):
            self.logger.debug(f"Processing batch {batch_idx + 1}/{len(batches)} with {len(batch)} items")
            batch_results = await self._process_batch(
                batch, 
                processor_func, 
                semaphore,
                effective_spacing
            )
            results.extend(batch_results)
            
            # Optional: Add spacing between batches as well
            if batch_idx < len(batches) - 1 and effective_spacing > 0:
                await asyncio.sleep(effective_spacing * 2)  # Longer pause between batches
        
        return results
    
    async def _process_batch(self,
                            batch: List[T],
                            processor_func: Callable[[T], Awaitable[R]],
                            semaphore: Optional[asyncio.Semaphore] = None,
                            spacing: float = 0.0) -> List[R]:
        """
        Process a single batch of items concurrently with request spacing.
        
        Args:
            batch: Batch of items to process
            processor_func: Async function to process each item
            semaphore: Optional semaphore for concurrency control
            spacing: Delay between starting each request
            
        Returns:
            List of results from processor function
        """
        if spacing > 0:
            # Process with spacing
            async def process_with_spacing(item, index):
                # Calculate staggered start time for this item
                start_delay = index * spacing
                
                # Wait for the staggered start
                await asyncio.sleep(start_delay)
                
                # Log when starting
                self.logger.debug(f"Starting item {index + 1}/{len(batch)} after {start_delay:.2f}s delay")
                
                # Process with semaphore if provided
                if semaphore:
                    async with semaphore:
                        return await processor_func(item)
                else:
                    return await processor_func(item)
            
            # Create tasks with staggered starts
            tasks = [
                asyncio.create_task(process_with_spacing(item, idx)) 
                for idx, item in enumerate(batch)
            ]
        else:
            # Original behavior without spacing
            if semaphore:
                async def process_with_semaphore(item):
                    async with semaphore:
                        return await processor_func(item)
                
                tasks = [asyncio.create_task(process_with_semaphore(item)) for item in batch]
            else:
                tasks = [asyncio.create_task(processor_func(item)) for item in batch]
        
        # Wait for all tasks to complete
        results = await asyncio.gather(*tasks, return_exceptions=self.retry_failed)
        
        # Track rate limit events if adaptive spacing is enabled
        if self.adaptive_spacing:
            await self._update_adaptive_spacing(results)
        
        return results
    
    async def _update_adaptive_spacing(self, results: List[Any]):
        """
        Update spacing based on rate limit events in results.
        
        Args:
            results: List of results from processing
        """
        current_time = time.time()
        
        # Clean old events outside the window
        self.rate_limit_events = [
            event_time for event_time in self.rate_limit_events 
            if current_time - event_time < self.rate_limit_window
        ]
        
        # Check for rate limit errors in results
        rate_limit_count = 0
        for result in results:
            if isinstance(result, Exception):
                # Check if it's a rate limit error (customize based on your error types)
                error_str = str(result).lower()
                if 'rate limit' in error_str or '429' in error_str:
                    rate_limit_count += 1
                    self.rate_limit_events.append(current_time)
        
        # Adjust spacing based on rate limit frequency
        if rate_limit_count > 0:
            # Increase spacing when hitting rate limits
            self.current_spacing = min(self.current_spacing * 1.5, self.max_spacing)
            self.logger.info(f"Rate limits detected. Increasing request spacing to {self.current_spacing:.2f}s")
        elif len(self.rate_limit_events) == 0 and self.current_spacing > self.min_spacing:
            # Gradually decrease spacing when no rate limits
            self.current_spacing = max(self.current_spacing * 0.9, self.min_spacing)
            self.logger.debug(f"No recent rate limits. Decreasing request spacing to {self.current_spacing:.2f}s")
    
    async def process_with_retry(self,
                                items: List[T],
                                processor_func: Callable[[T], Awaitable[R]],
                                should_retry: Callable[[T, Exception], bool] = None,
                                batch_size: Optional[int] = None) -> Dict[str, List]:
        """
        Process items with retry for failed items.
        
        Args:
            items: List of items to process
            processor_func: Async function to process each item
            should_retry: Function to determine if an item should be retried based on exception
            batch_size: Size of each batch (overrides default if provided)
            
        Returns:
            Dictionary with 'successful' and 'failed' lists
        """
        batch_size = batch_size or self.default_batch_size
        
        # Default retry function - retry all exceptions
        if should_retry is None:
            should_retry = lambda _, __: True
        
        # Track successful and failed items
        successful = []
        failed = []
        
        # Initial processing
        pending_items = [(item, 0) for item in items]  # (item, retry_count)
        
        # Process with retries
        for retry_round in range(self.max_retries + 1):
            if not pending_items:
                break
            
            # Increase spacing for retry rounds to be more conservative
            retry_spacing = self.current_spacing * (retry_round + 1) if self.adaptive_spacing else self.request_spacing
            
            current_batch = [item_data[0] for item_data in pending_items]
            results = await self.process_in_batches(
                current_batch, 
                processor_func, 
                batch_size,
                request_spacing=retry_spacing
            )
            
            # Process results and prepare next round
            new_pending_items = []
            
            for (item, retry_count), result in zip(pending_items, results):
                if isinstance(result, Exception):
                    # Item failed, check if it should be retried
                    if retry_count < self.max_retries and should_retry(item, result):
                        new_pending_items.append((item, retry_count + 1))
                    else:
                        failed.append((item, result))
                else:
                    # Item succeeded
                    successful.append(result)
            
            pending_items = new_pending_items
            
            # Add extra delay between retry rounds
            if pending_items and retry_spacing > 0:
                await asyncio.sleep(retry_spacing * 5)
        
        return {
            'successful': successful,
            'failed': failed
        }