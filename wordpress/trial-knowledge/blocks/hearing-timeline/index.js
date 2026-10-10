/**
 * Editor script for trial-knowledge/hearing-timeline. Rendering is server-side
 * (TK_Blocks), so the editor preview always matches the published output.
 */
import { registerBlockType } from '@wordpress/blocks';
import { InspectorControls, useBlockProps } from '@wordpress/block-editor';
import { PanelBody } from '@wordpress/components';
import ServerSideRender from '@wordpress/server-side-render';
import { __ } from '@wordpress/i18n';
import metadata from './block.json';

registerBlockType(metadata.name, {
	edit({ attributes, setAttributes }) {
		const blockProps = useBlockProps();
		return (
			<div {...blockProps}>
				<InspectorControls>
					<PanelBody title={__('הגדרות', 'trial-knowledge')}>
						<p>{__('אין הגדרות לבלוק זה.', 'trial-knowledge')}</p>
					</PanelBody>
				</InspectorControls>
				<ServerSideRender block={metadata.name} attributes={attributes} />
			</div>
		);
	},
	save: () => null,
});
